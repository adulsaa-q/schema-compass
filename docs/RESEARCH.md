# Research Foundations and Architecture

This document summarizes the academic literature, algorithms, and software engineering principles used in `schema-compass`.

---

## 1. Text-to-SQL and Schema Navigation

### 1.1 The Enterprise Gap vs. Benchmarks
Recent benchmarks (Spider 2.0, BIRD-Bench, BEAVER) show a clear gap between academic tests and production systems:
* **Academic Datasets:** Schemas are small (< 10 tables), clean, with full foreign key definitions and consistent naming.
* **Enterprise Reality:** Databases contain 200 to 2,000 tables, 50,000+ tokens of DDL, abbreviated names (`debcode`, `cust_id`), and often lack foreign key constraints because they were disabled for ETL performance.

### 1.2 Minimal Effective Context (MEC)
Dumping the full schema DDL into an LLM prompt exhausts context windows, increases latency, and triggers retrieval errors.
`schema-compass` uses the Minimal Effective Context (MEC) model:
1. **Search:** Candidate retrieval via BM25 and keyword heuristics.
2. **Induced Subgraph:** Graph expansion to connect candidate tables via shortest relational paths.
3. **Token Pruning:** Output compact table contracts (< 200 tokens per table) containing only primary keys, foreign keys, null rates, and sample values.

---

## 2. Graph Theory and Relational Join Topology

### 2.1 Schema as a Weighted Graph
We model the relational database as an undirected weighted graph $G = (V, E)$:
* **Vertices ($V$):** Relations / tables.
* **Edges ($E$):** Primary-to-Foreign Key or inferred relationships.
* **Edge Weights ($W(e)$):** Calculated from join certainty and selectivity:

$$W(e) = \alpha \cdot C_{\text{type}} + \beta \cdot \log_{10}(\max(\text{Cardinality}, 1)) + \gamma \cdot \text{NullRate}$$

| Relationship Type ($C_{\text{type}}$) | Weight Factor | Definition |
| :--- | :---: | :--- |
| **Declared FK** | `1.0` | Explicit constraint in system catalog |
| **Exact Name Match** | `1.3` | Same column name across tables (e.g. `customer_id`) |
| **Heuristic Pattern Match** | `1.8` | Naming convention match (e.g. `orders.customer_id` -> `customers.id`) |
| **Value Inclusion (IND)** | `2.2` | Data profiling shows >= 95% value containment |

### 2.2 Dijkstra vs. Minimum Steiner Tree
* **Two-table path ($k = 2$):** Solved with Dijkstra shortest path ($O(|E| + |V| \log |V|)$).
* **Multi-table join ($k \ge 3$):** Connecting $k$ tables is an instance of the Minimum Steiner Tree problem in graphs (NP-complete).
* **Algorithm:** We use the Kou-Markowsky-Berman (KMB) 2-approximation algorithm, running in $O(k \cdot |V|^2)$ time:
  1. Construct metric closure over the terminal nodes.
  2. Compute the Minimum Spanning Tree (MST) of the metric closure.
  3. Replace MST edges with the shortest paths in the original graph.
  4. Prune redundant non-terminal leaves.
  5. Traverse from the optimal root table (fact table heuristic) using BFS to output an ordered `JOIN ... ON` sequence.

---

## 3. AST-Based Deterministic Safety Gateway

### 3.1 Why Regex Fails
Regex matching fails against adversarial or complex SQL. Attack vectors bypass string checks via inline comments (`/* comment */ DROP TABLE`), hex literals, or subqueries (`WITH cte AS (DELETE ...) SELECT *`).

### 3.2 AST Traversal with `sqlglot`
`schema-compass` validates queries using `sqlglot` AST parsing:
* **Root Validation:** The root expression must be a `Select`.
* **Blocklist:** Any AST node matching `Insert`, `Update`, `Delete`, `Drop`, `Alter`, `Truncate`, `Execute`, or `Command` raises a validation error.
* **Query Rewriting:**
  * Appends `TOP <N>` (T-SQL) or `LIMIT <N>` (Postgres/DuckDB) if omitted.
  * Injects `WITH (NOLOCK)` on SQL Server to prevent transaction locks on production tables.
  * Rejects unconstrained Cartesian products (`CROSS JOIN` without join conditions or filters).

---

## 4. Software Engineering Standards

Following empirical software engineering practices:
1. **Reproducibility:** Environment managed via `uv` with locked dependencies (`uv.lock`) and explicit `pyproject.toml`.
2. **Test-Driven Development:**
   * Write failing tests before writing implementation code.
   * Red -> Green -> Refactor.
3. **Pragmatic Architecture:**
   * Use simple abstractions: `Function` -> `Dataclass / Pydantic` -> `Module`.
   * Avoid unnecessary OOP layers and deep inheritance.
4. **Progressive Disclosure:**
   * Return schema information in stages (`search_catalog` -> `get_table_contract` -> `get_join_tree`) to manage context size.

---

## 5. Dimensional Modeling Heuristics

Automated classification of tables in data warehouse environments:
* **Fact Tables:** Identified by high row counts, multiple outgoing foreign keys, numeric additive metrics, and references to date dimensions.
* **Dimension Tables:** Identified by lower row counts, surrogate keys, descriptive text columns, and slowly changing dimension (SCD) columns (`valid_from`, `valid_to`, `is_current`).
