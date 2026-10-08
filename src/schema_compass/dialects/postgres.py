from typing import Any

from schema_compass.models import ColumnInfo, Relationship, TableContract
from schema_compass.profiler.kimball import classify_table_role, refine_roles

GET_TABLES_SQL = """
SELECT
    table_schema AS schema_name,
    table_name
FROM information_schema.tables
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
  AND table_type = 'BASE TABLE'
ORDER BY table_schema, table_name;
"""

GET_COLUMNS_SQL = """
SELECT
    c.table_schema AS schema_name,
    c.table_name,
    c.column_name,
    c.data_type,
    c.is_nullable = 'YES' AS is_nullable,
    COALESCE(pk.is_pk, false) AS is_pk,
    COALESCE(fk.is_fk, false) AS is_fk
FROM information_schema.columns c
LEFT JOIN (
    SELECT
        kcu.table_schema,
        kcu.table_name,
        kcu.column_name,
        true AS is_pk
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_name = kcu.constraint_name
     AND tc.table_schema = kcu.table_schema
    WHERE tc.constraint_type = 'PRIMARY KEY'
) pk ON c.table_schema = pk.table_schema
    AND c.table_name = pk.table_name
    AND c.column_name = pk.column_name
LEFT JOIN (
    SELECT
        kcu.table_schema,
        kcu.table_name,
        kcu.column_name,
        true AS is_fk
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_name = kcu.constraint_name
     AND tc.table_schema = kcu.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
) fk ON c.table_schema = fk.table_schema
    AND c.table_name = fk.table_name
    AND c.column_name = fk.column_name
WHERE c.table_schema NOT IN ('pg_catalog', 'information_schema')
ORDER BY c.table_schema, c.table_name, c.ordinal_position;
"""

GET_FOREIGN_KEYS_SQL = """
SELECT
    tc.constraint_name AS fk_name,
    kcu.table_schema AS from_schema,
    kcu.table_name AS from_table,
    kcu.column_name AS from_column,
    ccu.table_schema AS to_schema,
    ccu.table_name AS to_table,
    ccu.column_name AS to_column
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
  ON tc.constraint_name = kcu.constraint_name
 AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage AS ccu
  ON ccu.constraint_name = tc.constraint_name
 AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY';
"""


class PostgresAdapter:
    def __init__(self, connection: Any = None) -> None:
        self.connection = connection

    @staticmethod
    def build_from_catalog_rows(
        tables: list[dict[str, Any]],
        columns: list[dict[str, Any]],
        foreign_keys: list[dict[str, Any]],
    ) -> list[TableContract]:
        # group columns by schema and table
        cols_by_table: dict[tuple[str, str], list[ColumnInfo]] = {}
        for c in columns:
            key = (c["schema_name"], c["table_name"])
            if key not in cols_by_table:
                cols_by_table[key] = []
            cols_by_table[key].append(
                ColumnInfo(
                    name=c["column_name"],
                    data_type=c["data_type"],
                    is_pk=bool(c.get("is_pk", False)),
                    is_fk=bool(c.get("is_fk", False)),
                    nullable=bool(c.get("is_nullable", True)),
                )
            )

        # group foreign keys by source table
        fks_by_table: dict[tuple[str, str], list[Relationship]] = {}
        for fk in foreign_keys:
            key = (fk["from_schema"], fk["from_table"])
            if key not in fks_by_table:
                fks_by_table[key] = []
            fks_by_table[key].append(
                Relationship(
                    source_table=fk["from_table"],
                    source_column=fk["from_column"],
                    target_table=fk["to_table"],
                    target_column=fk["to_column"],
                    relationship_type="declared_fk",
                    weight=1.0,
                )
            )

        contracts: list[TableContract] = []
        for t in tables:
            s_name = t["schema_name"]
            t_name = t["table_name"]
            r_count = int(t.get("row_count", 0))
            t_cols = cols_by_table.get((s_name, t_name), [])
            t_fks = fks_by_table.get((s_name, t_name), [])

            role = classify_table_role(
                table_name=t_name,
                columns=t_cols,
                row_count=r_count,
                outgoing_fks=len(t_fks),
            )

            contracts.append(
                TableContract(
                    name=t_name,
                    schema_name=s_name,
                    row_count=r_count,
                    role=role,
                    columns=t_cols,
                    relationships=t_fks,
                )
            )

        return refine_roles(contracts)

    def extract_contracts(self) -> list[TableContract]:
        if not self.connection:
            raise ValueError("No database connection configured for PostgresAdapter.")

        cursor = self.connection.cursor()
        cursor.execute(GET_TABLES_SQL)
        cols = [col[0] for col in cursor.description]
        tables_rows = [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]

        cursor.execute(GET_COLUMNS_SQL)
        cols = [col[0] for col in cursor.description]
        cols_rows = [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]

        cursor.execute(GET_FOREIGN_KEYS_SQL)
        cols = [col[0] for col in cursor.description]
        fks_rows = [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]

        return self.build_from_catalog_rows(tables_rows, cols_rows, fks_rows)
