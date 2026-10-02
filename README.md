# schema-compass

An open-source Model Context Protocol (MCP) server that helps AI coding agents query relational databases safely and efficiently. It builds a graph topology of your tables, finds minimal multi-table join paths using Steiner Tree algorithms, and parses every query through AST traversal to prevent accidental table locks and destructive operations.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![Model Context Protocol](https://img.shields.io/badge/MCP-Compatible-brightgreen.svg)](https://modelcontextprotocol.io/)

---

## Why This Exists

1. **Schema Overload:**
   Enterprise databases with 500+ tables blow up LLM context windows (50k+ tokens), causing high latency and hallucinations. `schema-compass` outputs Minimal Effective Context (MEC) contracts under 200 tokens per table, with column types, null rates, and sample values.

2. **Hallucinated Joins:**
   When foreign keys are missing or implicit, AI agents guess join conditions, producing Cartesian products or circular references. We model database relationships as an edge-weighted graph and calculate the Minimum Steiner Tree (KMB 2-approximation) to output exact `JOIN ... ON` clauses across any set of tables.

3. **Production Safety:**
   Unchecked agents can run slow unindexed queries, lock operational tables, or run unintended modifications. We inspect the `sqlglot` Abstract Syntax Tree to block non-SELECT statements, inject `TOP 100` or `LIMIT 100`, and automatically inject `WITH (NOLOCK)` for SQL Server.

---

## MCP Tools

- `search_catalog(query, top_k)`: Search tables, views, and columns using keyword heuristics.
- `get_join_tree(tables)`: Find the minimal join path connecting the requested tables and output the SQL `FROM ... JOIN ... ON` clause.
- `get_table_contract(table_name, mode)`: Return compact schema contracts with types, keys, and data samples.
- `explain_metric(metric_name)`: Return metric formulas, business logic, and upstream column lineage.
- `execute_safe_query(sql, dialect, max_rows)`: Validate through AST, clamp row limits, and inject table hints.

---

## Quickstart

```bash
# Clone repository
git clone https://github.com/adulsaa-q/schema-compass.git
cd schema-compass

# Install dependencies with uv
uv sync

# Run tests (37 tests across graph, solver, safety AST, profiler, and dialects)
uv run pytest
```

---

## Usage Modes

### 1. Offline Schema Mode (Zero-Risk for Enterprise)

You do not need a live database connection to use Schema-Compass. You can export table metadata (column names, keys, data types) to a JSON file once. No customer data or PII is ever exported.

```bash
# Export schema metadata from an SQLite database
uv run python -m schema_compass.export --db sqlite --path chinook.db --output chinook_schema.json

# Run MCP server using the offline JSON schema
uv run schema-compass --source json --path chinook_schema.json
```

### 2. Local SQLite Mode

Point Schema-Compass directly to an SQLite database file:

```bash
uv run schema-compass --source sqlite --path chinook.db
```

---

## MCP Client Configuration

### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "schema-compass": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/schema-compass",
        "run",
        "schema-compass",
        "--source",
        "json",
        "--path",
        "/absolute/path/to/schema_metadata.json"
      ]
    }
  }
}
```

### Cursor (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "schema-compass": {
      "command": "uv",
      "args": [
        "--directory",
        "D:\\dev\\PSN-Q\\schema-compass",
        "run",
        "schema-compass"
      ]
    }
  }
}
```

---

## Empirical Benchmarks

Run the built-in benchmarks:

```bash
# Multi-branch enterprise join benchmark (91.8% token savings)
uv run python evals/eval_join_benchmark.py

# Real-world 11-table Chinook database benchmark (5-hop join in 3.4ms)
uv run python evals/eval_chinook_showcase.py
```

---

## License

MIT (c) Adul Sa-a (Q)
