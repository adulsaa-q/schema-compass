# 🧭 Schema-Compass

> **The Intelligent Database Topology, Join-Path Navigator & AST Safety Gateway for AI Coding Agents**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![Model Context Protocol](https://img.shields.io/badge/MCP-Compatible-brightgreen.svg)](https://modelcontextprotocol.io/)
[![Zero AI Cost](https://img.shields.io/badge/AI%20Tokens-0.00%20Zero%20Cost-success.svg)](#architecture)

An open-source Model Context Protocol (MCP) server that gives AI Coding Agents (Claude Code, Cursor, Windsurf, Antigravity) an intelligent compass to navigate complex enterprise databases without schema hallucination or production risks.

---

## ⚡ The Core Problems It Solves

1. **Schema Overload & Context Exhaustion:**
   Enterprise databases with 500+ tables blow up LLM context windows (50k+ tokens), causing high latency and "Lost in the Middle" errors.
   * `schema-compass` returns **Minimal Effective Context (MEC)**: compact, token-efficient contracts (< 200 tokens per table) with data types, null rates, and sample values.

2. **Multi-Hop Join Ambiguity:**
   In schemas with implicit foreign keys or missing constraints, agents hallucinate joins, creating Cartesian products or circular loops.
   * `schema-compass` models the database as a weighted topology graph and computes the **Minimum Steiner Tree (KMB 2-Approximation Algorithm)** to give agents the mathematically optimal `JOIN ... ON` path across $k$ tables in milliseconds.

3. **Production Safety & Locking:**
   Unchecked agents can run slow unindexed queries, lock operational tables, or execute destructive DML.
   * `schema-compass` uses **`sqlglot` AST Traversal** to strictly enforce read-only execution, inject `TOP 100` / `LIMIT 100`, enforce statement timeouts, and automatically inject `WITH (NOLOCK)` on SQL Server.

---

## 🛠️ Core MCP Tools

- `search_catalog(query, top_k)`: Local heuristic & BM25 catalog search over tables, views, and columns.
- `get_join_tree(tables)`: Computes the minimal Steiner join tree connecting all requested tables and returns clean SQL `FROM ... JOIN ... ON`.
- `get_table_contract(table_name, mode)`: Returns a compact schema summary with data types, null rates, and sample values.
- `explain_metric(metric_name)`: Returns business definition, calculation formula, and upstream lineage.
- `execute_safe_query(sql, max_rows)`: Validates via AST, injects safety clamps, and executes via read-only connection.

---

## 🚀 Quickstart

```bash
# Clone repository
git clone https://github.com/adulsaa-q/schema-compass.git
cd schema-compass

# Setup environment with uv
uv sync

# Run test suite
uv run pytest
```

---

## 📄 License

MIT © Adul Sa-a (Q)
