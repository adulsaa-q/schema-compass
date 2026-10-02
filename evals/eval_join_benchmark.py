import sys
import time
from pathlib import Path

# Ensure project root is in sys.path and stdout is UTF-8 on Windows
sys.path.insert(0, str(Path(__file__).parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from schema_compass.graph.schema_graph import SchemaGraph
from schema_compass.graph.steiner_solver import SteinerJoinSolver
from tests.fixtures.sample_schema import SAMPLE_TABLES


def run_benchmark():
    print("=" * 60)
    print("[*] SCHEMA-COMPASS EMPIRICAL EVALUATION & BENCHMARK")
    print("=" * 60)

    # 1. Topology Graph Construction
    start = time.perf_counter()
    sg = SchemaGraph()
    sg.load_tables(list(SAMPLE_TABLES.values()))
    load_time_ms = (time.perf_counter() - start) * 1000
    print(f"[*] Loaded {len(sg.tables)} tables into Topology Graph in: {load_time_ms:.3f} ms")

    solver = SteinerJoinSolver(sg)

    # 2. Benchmark Multi-Hop Dijkstra (2 tables)
    start = time.perf_counter()
    path = sg.get_shortest_path("order_items", "countries")
    dijkstra_time_ms = (time.perf_counter() - start) * 1000
    print(f"[*] 4-Hop Dijkstra Path ({' -> '.join(path)}): {dijkstra_time_ms:.3f} ms")

    # 3. Benchmark Steiner Minimal Join Tree (3 terminals across disparate branches)
    terminals = ["order_items", "customers", "categories"]
    start = time.perf_counter()
    join_tree = solver.solve(terminals)
    steiner_time_ms = (time.perf_counter() - start) * 1000
    print(f"[*] 3-Terminal Steiner Minimal Join Tree: {steiner_time_ms:.3f} ms")
    print(f"    - Included Tables: {', '.join(join_tree.tables_included)}")
    print(f"    - Total Cost: {join_tree.total_weight:.2f}")

    # 4. Token Reduction Metric (Raw DDL vs Induced Join Tree)
    raw_ddl_char_count = sum(
        len(c.name) * 20 + sum(len(col.name) + len(col.data_type) + 20 for col in c.columns)
        for c in SAMPLE_TABLES.values()
    )
    raw_ddl_est_tokens = raw_ddl_char_count // 4

    sql_from = join_tree.to_sql_from_clause()
    join_tree_est_tokens = len(sql_from) // 4
    token_saving_pct = (1 - (join_tree_est_tokens / raw_ddl_est_tokens)) * 100

    print("-" * 60)
    print("[TOKEN EFFICIENCY BENCHMARK]")
    print(f"    - Raw Full Schema DDL Dump: ~{raw_ddl_est_tokens:,} tokens")
    print(f"    - Schema-Compass JOIN Clause: ~{join_tree_est_tokens} tokens")
    print(f"    - Context Reduction: {token_saving_pct:.1f}% SAVED")
    print("-" * 60)
    print("\n[Generated Clean SQL Join Block]")
    print(sql_from)
    print("=" * 60)


if __name__ == "__main__":
    run_benchmark()
