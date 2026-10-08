from typing import Any

from schema_compass.models import ColumnInfo, Relationship, TableContract
from schema_compass.profiler.kimball import classify_table_role, refine_roles

GET_TABLES_SQL = """
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

SELECT
    s.name AS schema_name,
    t.name AS table_name,
    ISNULL(p.rows, 0) AS row_count
FROM sys.tables t
INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
OUTER APPLY (
    SELECT SUM(p.rows) AS rows
    FROM sys.partitions p
    WHERE p.object_id = t.object_id AND p.index_id IN (0, 1)
) p
WHERE t.is_ms_shipped = 0
ORDER BY s.name, t.name;
"""

GET_COLUMNS_SQL = """
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

SELECT
    s.name AS schema_name,
    t.name AS table_name,
    c.name AS column_name,
    tp.name AS data_type,
    c.is_nullable,
    ISNULL(pk.is_pk, 0) AS is_pk,
    ISNULL(fk.is_fk, 0) AS is_fk
FROM sys.columns c
INNER JOIN sys.tables t ON c.object_id = t.object_id
INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
INNER JOIN sys.types tp ON c.user_type_id = tp.user_type_id
LEFT JOIN (
    SELECT DISTINCT ic.object_id, ic.column_id, 1 AS is_pk
    FROM sys.index_columns ic
    INNER JOIN sys.indexes i ON ic.object_id = i.object_id AND ic.index_id = i.index_id
    WHERE i.is_primary_key = 1
) pk ON c.object_id = pk.object_id AND c.column_id = pk.column_id
LEFT JOIN (
    SELECT DISTINCT fkc.parent_object_id AS object_id, fkc.parent_column_id AS column_id, 1 AS is_fk
    FROM sys.foreign_key_columns fkc
) fk ON c.object_id = fk.object_id AND c.column_id = fk.column_id
WHERE t.is_ms_shipped = 0
ORDER BY s.name, t.name, c.column_id;
"""

GET_FOREIGN_KEYS_SQL = """
SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED;

SELECT DISTINCT
    fk.name AS fk_name,
    s_from.name AS from_schema,
    t_from.name AS from_table,
    c_from.name AS from_column,
    s_to.name AS to_schema,
    t_to.name AS to_table,
    c_to.name AS to_column
FROM sys.foreign_keys fk
INNER JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
INNER JOIN sys.tables t_from ON fkc.parent_object_id = t_from.object_id
INNER JOIN sys.schemas s_from ON t_from.schema_id = s_from.schema_id
INNER JOIN sys.columns c_from ON fkc.parent_object_id = c_from.object_id AND fkc.parent_column_id = c_from.column_id
INNER JOIN sys.tables t_to ON fkc.referenced_object_id = t_to.object_id
INNER JOIN sys.schemas s_to ON t_to.schema_id = s_to.schema_id
INNER JOIN sys.columns c_to ON fkc.referenced_object_id = c_to.object_id AND fkc.referenced_column_id = c_to.column_id;
"""


class MSSQLAdapter:
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

        # group foreign keys by parent table
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
            raise ValueError("No database connection configured for MSSQLAdapter.")

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
