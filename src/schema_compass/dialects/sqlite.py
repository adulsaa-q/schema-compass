import sqlite3

from schema_compass.models import ColumnInfo, Relationship, TableContract
from schema_compass.profiler.kimball import classify_table_role


class SQLiteAdapter:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def extract_contracts(self) -> list[TableContract]:
        cursor = self.connection.cursor()

        # query sqlite_master for user tables
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        table_names = [row[0] for row in cursor.fetchall()]

        contracts: list[TableContract] = []

        for table_name in table_names:
            # PRAGMA table_info returns: cid, name, type, notnull, dflt_value, pk
            cursor.execute(f'PRAGMA table_info("{table_name}")')
            col_rows = cursor.fetchall()

            # PRAGMA foreign_key_list returns: id, seq, table, from, to, on_update, on_delete, match
            cursor.execute(f'PRAGMA foreign_key_list("{table_name}")')
            fk_rows = cursor.fetchall()

            fk_columns = {row[3] for row in fk_rows}
            relationships = [
                Relationship(
                    source_table=table_name,
                    source_column=row[3],
                    target_table=row[2],
                    target_column=row[4],
                    relationship_type="declared_fk",
                    weight=1.0,
                )
                for row in fk_rows
            ]

            columns: list[ColumnInfo] = []
            for col in col_rows:
                c_name = col[1]
                c_type = col[2] or "TEXT"
                c_notnull = bool(col[3])
                c_pk = bool(col[5])
                c_fk = c_name in fk_columns

                columns.append(
                    ColumnInfo(
                        name=c_name,
                        data_type=c_type,
                        is_pk=c_pk,
                        is_fk=c_fk,
                        nullable=not c_notnull,
                    )
                )

            # count table rows for cardinality scoring
            cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
            row_count_val = cursor.fetchone()
            row_count = row_count_val[0] if row_count_val else 0

            # classify role using Kimball heuristics
            role = classify_table_role(
                table_name=table_name,
                columns=columns,
                row_count=row_count,
                outgoing_fks=len(relationships),
            )

            contracts.append(
                TableContract(
                    name=table_name,
                    schema_name="main",
                    row_count=row_count,
                    role=role,
                    columns=columns,
                    relationships=relationships,
                )
            )

        return contracts
