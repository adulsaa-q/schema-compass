import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from schema_compass.dialects.sqlite import SQLiteAdapter
from schema_compass.graph.schema_graph import SchemaGraph
from schema_compass.graph.steiner_solver import SteinerJoinSolver
from schema_compass.profiler.contract import format_contract
from schema_compass.safety.ast_guard import ASTGuard

CHINOOK_DDL = """
CREATE TABLE artists (
    ArtistId INTEGER PRIMARY KEY,
    Name TEXT
);

CREATE TABLE albums (
    AlbumId INTEGER PRIMARY KEY,
    Title TEXT NOT NULL,
    ArtistId INTEGER NOT NULL,
    FOREIGN KEY (ArtistId) REFERENCES artists (ArtistId)
);

CREATE TABLE genres (
    GenreId INTEGER PRIMARY KEY,
    Name TEXT
);

CREATE TABLE media_types (
    MediaTypeId INTEGER PRIMARY KEY,
    Name TEXT
);

CREATE TABLE tracks (
    TrackId INTEGER PRIMARY KEY,
    Name TEXT NOT NULL,
    AlbumId INTEGER,
    MediaTypeId INTEGER NOT NULL,
    GenreId INTEGER,
    UnitPrice REAL NOT NULL,
    FOREIGN KEY (AlbumId) REFERENCES albums (AlbumId),
    FOREIGN KEY (MediaTypeId) REFERENCES media_types (MediaTypeId),
    FOREIGN KEY (GenreId) REFERENCES genres (GenreId)
);

CREATE TABLE employees (
    EmployeeId INTEGER PRIMARY KEY,
    LastName TEXT NOT NULL,
    FirstName TEXT NOT NULL,
    ReportsTo INTEGER,
    FOREIGN KEY (ReportsTo) REFERENCES employees (EmployeeId)
);

CREATE TABLE customers (
    CustomerId INTEGER PRIMARY KEY,
    FirstName TEXT NOT NULL,
    LastName TEXT NOT NULL,
    SupportRepId INTEGER,
    FOREIGN KEY (SupportRepId) REFERENCES employees (EmployeeId)
);

CREATE TABLE invoices (
    InvoiceId INTEGER PRIMARY KEY,
    CustomerId INTEGER NOT NULL,
    InvoiceDate TEXT NOT NULL,
    Total REAL NOT NULL,
    FOREIGN KEY (CustomerId) REFERENCES customers (CustomerId)
);

CREATE TABLE invoice_items (
    InvoiceLineId INTEGER PRIMARY KEY,
    InvoiceId INTEGER NOT NULL,
    TrackId INTEGER NOT NULL,
    UnitPrice REAL NOT NULL,
    Quantity INTEGER NOT NULL,
    FOREIGN KEY (InvoiceId) REFERENCES invoices (InvoiceId),
    FOREIGN KEY (TrackId) REFERENCES tracks (TrackId)
);

CREATE TABLE playlists (
    PlaylistId INTEGER PRIMARY KEY,
    Name TEXT
);

CREATE TABLE playlist_track (
    PlaylistId INTEGER NOT NULL,
    TrackId INTEGER NOT NULL,
    PRIMARY KEY (PlaylistId, TrackId),
    FOREIGN KEY (PlaylistId) REFERENCES playlists (PlaylistId),
    FOREIGN KEY (TrackId) REFERENCES tracks (TrackId)
);
"""


def run_chinook_showcase():
    print("=" * 65)
    print("  SCHEMA-COMPASS: REAL-WORLD CHINOOK DATABASE BENCHMARK")
    print("=" * 65)

    # 1. Initialize SQLite Database
    conn = sqlite3.connect(":memory:")
    conn.executescript(CHINOOK_DDL)

    # 2. Extract Schema Metadata via SQLiteAdapter
    start = time.perf_counter()
    adapter = SQLiteAdapter(conn)
    contracts = adapter.extract_contracts()
    extract_time_ms = (time.perf_counter() - start) * 1000

    print(f"[+] Extracted {len(contracts)} tables from SQLite catalog in: {extract_time_ms:.3f} ms")

    # 3. Build Schema Topology Graph
    graph = SchemaGraph()
    graph.load_tables(contracts)
    print(f"[+] Relational graph constructed with {len(graph.tables)} nodes")

    # 4. Solve Multi-Hop Join (Artists to Invoices - 5 Hops)
    print("\n--- [Scenario: Query Total Sales by Artist Name] ---")
    terminals = ["artists", "invoices"]
    start = time.perf_counter()
    solver = SteinerJoinSolver(graph)
    join_tree = solver.solve(terminals)
    solve_time_ms = (time.perf_counter() - start) * 1000

    print(f"[+] Computed Steiner Join Tree in: {solve_time_ms:.3f} ms")
    print(f"    Tables traversed: {' -> '.join(join_tree.tables_included)}")
    print(f"    Total Steiner edge weight: {join_tree.total_weight:.2f}")

    sql_from = join_tree.to_sql_from_clause()
    print("\n[+] Generated SQL JOIN Clause:")
    for line in sql_from.splitlines():
        print(f"    {line}")

    # 5. AST Guard Validation and Safety Rewrite
    guard = ASTGuard()
    raw_query = f"SELECT artists.Name, SUM(invoice_items.UnitPrice * invoice_items.Quantity) AS TotalSales {sql_from} GROUP BY artists.Name"
    safe_sql = guard.rewrite(raw_query, dialect="tsql", max_rows=100)
    print("\n[+] AST Guard Rewritten Safe Query (T-SQL WITH NOLOCK + TOP 100):")
    for line in safe_sql.splitlines():
        print(f"    {line}")

    # 6. Minimal Effective Context (MEC) Token Savings
    raw_ddl_tokens = len(CHINOOK_DDL) // 4
    mec_contracts = "\n".join(format_contract(c, mode="compact") for c in contracts[:2])
    mec_tokens = len(mec_contracts) // 4

    print("\n[+] Token Efficiency Benchmark:")
    print(f"    - Full Chinook Schema DDL: ~{raw_ddl_tokens:,} tokens")
    print(f"    - MEC Compact Contract (2 tables): ~{mec_tokens} tokens")
    savings_pct = (1 - (mec_tokens / raw_ddl_tokens)) * 100
    print(f"    - Token Reduction: {savings_pct:.1f}% SAVED")
    print("=" * 65)


if __name__ == "__main__":
    run_chinook_showcase()
