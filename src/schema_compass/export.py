import argparse
import json
import sqlite3
from pathlib import Path

from schema_compass.dialects.sqlite import SQLiteAdapter
from schema_compass.models import TableContract


def export_schema_to_json(
    source_type: str,
    path: str,
    output_path: str,
) -> list[TableContract]:
    stype = source_type.lower()
    if stype == "sqlite":
        conn = sqlite3.connect(path)
        try:
            adapter = SQLiteAdapter(conn)
            contracts = adapter.extract_contracts()
        finally:
            conn.close()
    else:
        raise ValueError(f"Unsupported source type for export: {source_type}")

    serialized = [c.model_dump() for c in contracts]
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(serialized, f, indent=2, default=str)

    return contracts


def main() -> None:
    parser = argparse.ArgumentParser(description="Export database schema metadata to offline JSON")
    parser.add_argument("--db", choices=["sqlite"], default="sqlite", help="Database type")
    parser.add_argument("--path", required=True, help="Path to database")
    parser.add_argument("--output", default="schema_metadata.json", help="Output JSON path")
    args = parser.parse_args()

    contracts = export_schema_to_json(args.db, args.path, args.output)
    print(f"Exported {len(contracts)} tables to {args.output}")


if __name__ == "__main__":
    main()
