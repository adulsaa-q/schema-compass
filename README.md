# schema-compass

An open-source Model Context Protocol (MCP) server that acts as a schema topology navigator and deterministic AST safety gateway between AI coding agents (Claude Code, Cursor, Windsurf, Antigravity) and relational databases (SQL Server, PostgreSQL, SQLite, DuckDB).

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![Model Context Protocol](https://img.shields.io/badge/MCP-Compatible-brightgreen.svg)](https://modelcontextprotocol.io/)
[![Tests: 92 Passed](https://img.shields.io/badge/Tests-92%20Passed-brightgreen.svg)](tests/)
[![Ruff: Clean](https://img.shields.io/badge/Ruff-Compliant-brightgreen.svg)](https://astral.sh/ruff)

---

## Why Schema-Compass Exists

### 1. Schema Overload (50,000+ Tokens to Under 200 Tokens)
Enterprise databases with hundreds of tables exceed LLM context windows, leading to context truncation, high API costs, and severe hallucination rates. 

Schema-Compass implements **Minimal Effective Context (MEC)**:
- Instead of dumping raw DDLs, it serves compact table contracts under 200 tokens per table.
- Contracts include column types, null rates, data samples, and inlined foreign key relationships (e.g. `- customer_id: INT (FK -> customers.customer_id)`).

### 2. Hallucinated Joins and Cartesian Disasters
When database schemas lack foreign keys or rely on implicit naming conventions, AI agents frequently hallucinate join keys or write accidental Cartesian products.

Schema-Compass models your relational schema as an edge-weighted graph:
- Computes multi-table join paths using the **Kou-Markowsky-Berman (KMB) Minimum Steiner Tree 2-approximation algorithm**.
- Applies **Kimball dimensional heuristics** to select the natural Fact table as the query root, generating exact `FROM fact ... JOIN dim ... ON ...` SQL sequences in under 4ms.

### 3. Enterprise Database Privacy (Zero Production Server Risk)
Many data teams cannot connect AI agents directly to corporate production servers due to security policies, network firewalls, and data privacy regulations.

Schema-Compass features **Offline Schema Mode**:
- Extract table names, column types, and constraints once into an offline JSON contract.
- **Zero data, zero PII, and zero sensitive records** are ever extracted; only metadata is captured.
- AI agents run completely offline against the local JSON metadata file. No network connection to your live server is needed.

### 4. Deterministic AST Safety Gateway
Regex filters fail against obfuscated SQL and subquery attacks. Schema-Compass parses every query using `sqlglot` Abstract Syntax Tree (AST) validation:
- **Strict Read-Only Enforcement:** Blocks all DDL/DML operations (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `MERGE`, `EXECUTE`).
- **Dangerous Procedure Blocklist:** Blocks remote execution and exfiltration functions (`xp_cmdshell`, `sp_OACreate`, `OPENROWSET`, `OPENDATASOURCE`, `OPENQUERY`, `load_extension`, `pg_read_file`).
- **Cartesian Join Detection:** Flags unconstrained comma joins and cross joins even when disguised behind subqueries or trivial `WHERE 1 = 1` clauses.
- **Non-Breaking Table Hints:** Injects `WITH (NOLOCK)` on physical SQL Server tables while automatically filtering out Table-Valued Functions (`STRING_SPLIT`, `OPENJSON`) and table variables (`@var`).
- **Deterministic Row Limits:** Enforces positive row limits (`TOP 100` / `LIMIT 100`) while preserving smaller user limits (`TOP (5)` or `FETCH NEXT 5 ROWS`).

---

## System Architecture

```mermaid
flowchart LR
    A["AI Coding Agent<br/>(Claude Code, Cursor, Windsurf)"] <-->|JSON-RPC / stdio| B["FastMCP Server<br/>(schema-compass)"]
    
    subgraph Engine ["Core Engine"]
        B <--> C["Graph Engine<br/>(Steiner Solver & KMB)"]
        B <--> D["AST Safety Gateway<br/>(sqlglot Guard & Rewriter)"]
        B <--> E["Kimball Profiler<br/>(MEC Compact Contracts)"]
    end

    subgraph DataSources ["Metadata Sources"]
        Engine <--> F[("Offline JSON Contract<br/>(Zero Server Risk)")]
        Engine <--> G[("Local SQLite / DuckDB")]
        Engine <--> H[("SQL Server / Postgres<br/>(Catalog DMVs)")]
    end
```

---

## MCP Tools Reference

| Tool Name | Parameters | Output | Description |
| :--- | :--- | :--- | :--- |
| `search_catalog` | `query: str`, `top_k: int = 5` | Markdown List | Search tables, views, and columns using lexical match heuristics. |
| `get_join_tree` | `tables: list[str]` | SQL Code Block | Solves Minimum Steiner Join Tree and outputs exact `FROM ... JOIN ... ON` syntax. |
| `get_table_contract` | `table_name: str`, `mode: str = 'compact'` | MEC Markdown | Returns compact column types, keys, sample values, and inlined FK references. |
| `explain_metric` | `metric_name: str` | Lineage Summary | Provides business definitions, formulas, and upstream table/column lineage. |
| `execute_safe_query` | `sql: str`, `dialect: str = 'tsql'`, `max_rows: int = 100` | Table / Results | Validates query through AST, injects hints, clamps limits, and executes safely. |

---

## Quickstart

### Prerequisites
- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/) (recommended package manager)

```bash
# Clone the repository
git clone https://github.com/adulsaa-q/schema-compass.git
cd schema-compass

# Install dependencies with uv
uv sync

# Run the complete test suite (92 tests passed in ~2s)
uv run pytest
```

---

## Usage Modes

### Mode 1: Offline Schema Metadata (Zero-Risk Enterprise)
Export catalog metadata to an offline JSON file. You can commit this file to your repository or keep it on your workstation:

```bash
# Export metadata from an SQLite database
uv run python -m schema_compass.export --db sqlite --path chinook.db --output chinook_schema.json

# Run MCP server using the offline JSON contract
uv run schema-compass --source json --path chinook_schema.json
```

### Mode 2: Local SQLite / DuckDB Database
Point Schema-Compass directly to a local database file:

```bash
uv run schema-compass --source sqlite --path chinook.db
```

### Mode 3: Direct Database Catalog
Schema-Compass can connect directly to SQL Server or PostgreSQL to inspect system metadata (`INFORMATION_SCHEMA` and system DMVs) using non-blocking read uncommitted queries:

```bash
# SQL Server (T-SQL)
uv run schema-compass --source mssql --conn "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;DATABASE=mydb;UID=sa;PWD=secret;TrustServerCertificate=yes;"

# PostgreSQL
uv run schema-compass --source postgres --conn "postgresql://postgres:secret@localhost:5432/mydb"
```

---

## MCP Client Configuration

### 1. Claude Code CLI
Add Schema-Compass to Claude Code with a single command:

```bash
claude mcp add schema-compass -- uv --directory /absolute/path/to/schema-compass run schema-compass --source json --path /absolute/path/to/schema.json
```

### 2. Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "schema-compass": {
      "command": "uv",
      "args": [
        "--directory",
        "D:\\dev\\PSN-Q\\schema-compass",
        "run",
        "schema-compass",
        "--source",
        "json",
        "--path",
        "D:\\dev\\PSN-Q\\schema-compass\\chinook_schema.json"
      ]
    }
  }
}
```

### 3. Cursor (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "schema-compass": {
      "command": "uv",
      "args": [
        "--directory",
        "D:\\dev\\PSN-Q\\schema-compass",
        "run",
        "schema-compass",
        "--source",
        "json",
        "--path",
        "D:\\dev\\PSN-Q\\schema-compass\\chinook_schema.json"
      ]
    }
  }
}
```

### 4. Windsurf (`~/.codeium/windsurf/mcp_config.json`)

```json
{
  "mcpServers": {
    "schema-compass": {
      "command": "uv",
      "args": [
        "--directory",
        "D:\\dev\\PSN-Q\\schema-compass",
        "run",
        "schema-compass",
        "--source",
        "json",
        "--path",
        "D:\\dev\\PSN-Q\\schema-compass\\chinook_schema.json"
      ]
    }
  }
}
```

---

## Empirical Benchmarks

Run the built-in benchmark scripts:

```bash
# Real-world 11-table Chinook database benchmark (5-hop join in 3.195ms, 87.9% token savings)
uv run python evals/eval_chinook_showcase.py

# Multi-branch enterprise join benchmark (91.8% token savings)
uv run python evals/eval_join_benchmark.py
```

### Benchmark Results (Chinook Database)
- **Metadata Extraction Time:** 1.258 ms (11 tables)
- **5-Hop Join Tree Calculation:** 3.195 ms
- **Token Efficiency:** Reduced prompt tokens from 511 tokens (raw DDL) down to 62 tokens (MEC contract), delivering an **87.9% token reduction**.

---

## Testing and Security Audits

The test suite covers unit logic, graph theory edge cases, and adversarial evasion vectors:

```bash
uv run pytest -v
```

```
tests/test_adversarial_qa.py ........................................... [ 46%]
tests/test_dialects.py .....                                             [ 52%]
tests/test_profiler.py .....                                             [ 57%]
tests/test_safety.py ...................                                 [ 78%]
tests/test_schema_graph.py .....                                         [ 83%]
tests/test_server.py .........                                           [ 93%]
tests/test_steiner_solver.py ......                                      [100%]

============================= 92 passed in 2.03s ==============================
```

- **43 Adversarial Attack Vectors:** Multi-statement bypasses, subquery mutations, OOB exfiltration (`OPENROWSET`, `xp_cmdshell`), Cartesian explosion bypasses, and cyclic topology tests.
- **Linting & Type Safety:** 100% compliant with `ruff check` and `ruff format`.

---

## License

MIT License. Copyright (c) 2026 Adul Sa-a (Q).
