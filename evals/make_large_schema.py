"""Build a large SQLite database: the real Chinook tables plus ~960 synthetic enterprise-style tables.

The extra tables are random (names, columns and foreign keys inside a domain) and empty, so they add
schema size without changing any answer. Five look-alike tables (invoice_archive_2015, ...) are
included as decoys.

    uv run python evals/make_large_schema.py Chinook_Sqlite.sqlite large.sqlite
"""

import random
import sqlite3
import sys
from pathlib import Path

src_path, out_path = Path(sys.argv[1]), Path(sys.argv[2])
rnd = random.Random(7)
out_path.unlink(missing_ok=True)
db = sqlite3.connect(out_path)
db.execute("ATTACH DATABASE ? AS src", (str(src_path),))

# 1. real Chinook tables, with data
for name, sql in db.execute(
    "select name, sql from src.sqlite_master where type='table'"
).fetchall():
    db.execute(sql)
    db.execute(f'INSERT INTO main."{name}" SELECT * FROM src."{name}"')
real = {r[0] for r in db.execute("select name from main.sqlite_master where type='table'")}

# 2. synthetic noise: 12 domains x 24 entities, foreign keys stay inside a domain
domains = [
    "hr",
    "fin",
    "inv",
    "crm",
    "mkt",
    "log",
    "prc",
    "sup",
    "qa",
    "prj",
    "legal",
    "it",
    "ops",
    "sales",
    "eng",
    "fac",
    "trn",
    "rsk",
    "cmp",
    "aud",
    "rd",
    "cs",
    "pay",
    "tax",
    "trd",
    "wms",
    "tms",
    "bi",
    "dw",
    "ext",
    "gl",
    "ap",
    "ar",
    "fa",
    "pm",
    "hs",
    "env",
    "qc",
    "ec",
    "ws",
]
entities = [
    "account",
    "address",
    "adjustment",
    "alert",
    "allocation",
    "approval",
    "asset",
    "audit",
    "batch",
    "budget",
    "calendar",
    "campaign",
    "category",
    "channel",
    "claim",
    "contact",
    "contract",
    "coupon",
    "currency",
    "customer",
    "department",
    "document",
    "event",
    "expense",
    "forecast",
    "invoice",
    "item",
    "journal",
    "ledger",
    "location",
    "message",
    "note",
    "order",
    "payment",
    "plan",
    "policy",
    "product",
    "quote",
    "region",
    "report",
    "request",
    "schedule",
    "shipment",
    "task",
    "ticket",
    "track",
    "transaction",
    "vendor",
]
attrs = [
    ("code", "TEXT"),
    ("notes", "TEXT"),
    ("is_active", "INTEGER"),
    ("qty", "INTEGER"),
    ("amount", "REAL"),
    ("priority", "INTEGER"),
    ("owner", "TEXT"),
    ("source", "TEXT"),
    ("updated_at", "TEXT"),
    ("score", "REAL"),
    ("currency", "TEXT"),
    ("external_ref", "TEXT"),
    ("start_date", "TEXT"),
    ("end_date", "TEXT"),
]
made = 0
for d in domains:
    done: list[str] = []
    for e in rnd.sample(entities, 24):
        name = f"{d}_{e}"
        cols = [
            f"{name}_id INTEGER PRIMARY KEY",
            f"{e}_name TEXT",
            "status TEXT",
            "created_at TEXT",
        ]
        fks = []
        for parent in rnd.sample(done, min(len(done), rnd.choice([0, 1, 1, 2, 3]))):
            cols.append(f"{parent}_id INTEGER")
            fks.append(f"FOREIGN KEY ({parent}_id) REFERENCES {parent} ({parent}_id)")
        for a, t in rnd.sample(attrs, rnd.randint(3, 8)):
            cols.append(f"{a} {t}")
        db.execute(f"CREATE TABLE {name} ({', '.join(cols + fks)})")
        done.append(name)
        made += 1

# 3. look-alikes of the real tables, as legacy systems tend to leave behind
for name in [
    "invoice_archive_2015",
    "customer_legacy_import",
    "track_staging",
    "genre_map",
    "employee_hist",
]:
    db.execute(
        f"CREATE TABLE {name} (id INTEGER PRIMARY KEY, ref_id INTEGER, payload TEXT, loaded_at TEXT)"
    )
db.commit()

n = db.execute("select count(*) from main.sqlite_master where type='table'").fetchone()[0]
ddl = "\n".join(
    r[0] + ";" for r in db.execute("select sql from main.sqlite_master where type='table'")
)
print(
    f"tables: {n} (real {len(real)}, synthetic {made}, look-alikes 5); DDL {len(ddl):,} chars (~{len(ddl) // 4:,} tokens)"
)
