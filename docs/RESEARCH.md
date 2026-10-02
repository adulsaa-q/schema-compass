# 🔬 Research Foundations & Engineering Blueprint

This document codifies the academic literature, mathematical foundations, and empirical software engineering principles governing `schema-compass`. Every AI agent working on this codebase must understand and abide by these principles.

---

## 1. The Text-to-SQL & Schema Navigation Problem

### 1.1 The Enterprise Reality vs. Academic Benchmark Cliff
Recent benchmarks—specifically **Spider 2.0**, **BIRD-Bench**, and **BEAVER (2025/2026)**—highlight a massive divergence between academic evaluation and enterprise deployment:
* **Academic Datasets:** Schemas are small (< 10 tables), clean, with 100% declared foreign keys and normalized names.
* **Enterprise Reality:** Databases contain 200–2,000 tables, 50,000+ tokens of DDL, abbreviated column names (`debcode`, `cust_id`), and **no declared foreign keys** (disabled for ETL performance).

### 1.2 Minimal Effective Context (MEC)
Dumping the full schema DDL exhausts the LLM's context window, introduces high latency, and triggers the "Lost in the Middle" failure mode.
`schema-compass` adheres to the **Minimal Effective Context (MEC)** paradigm (proven in SOTA models like **CHESS**, **DAIL-SQL**, and **GenLink**):
1. **Search:** Candidate retrieval via BM25 and keyword heuristics.
2. **Induced Subgraph:** Graph expansion to connect candidate tables via shortest relational paths.
3. **Token Pruning:** Outputting compact table contracts (< 200 tokens per table) containing only primary/foreign keys, null rates, and sample values.

---

## 2. Graph Theory & Relational Join Topology

### 2.1 Schema as a Weighted Graph
A relational database is modeled as an undirected weighted graph $G = (V, E)$:
* **Vertices ($V$):** Relations / tables.
* **Edges ($E$):** Primary-to-Foreign Key or inferred relationships.
* **Edge Weights ($W(e)$):** Calculated based on join certainty and selectivity:

$$W(e) = \alpha \cdot C_{\text{type}} + \beta \cdot \log_{10}(\text{Cardinality}) + \gamma \cdot \text{NullRate}$$

| Relationship Type ($C_{\text{type}}$) | Weight Factor | Definition |
| :--- | :---: | :--- |
| **Declared FK** | `1.0` | Explicit constraint in system catalog |
| **Exact Name Match** | `1.3` | Same column name across tables (e.g. `customer_id`) |
| **Heuristic Pattern Match** | `1.8` | Naming convention match (e.g. `orders.customer_id` $\rightarrow$ `customers.id`) |
| **Value Inclusion (IND)** | `2.2` | Data profiling shows $\ge 95\%$ value containment |

### 2.2 Dijkstra vs. Minimum Steiner Tree
* **Two-table path ($k = 2$):** Solved via Dijkstra's shortest path algorithm ($O(|E| + |V| \log |V|)$).
* **Multi-table join ($k \ge 3$):** Connecting $k$ disparate terminal tables is an instance of the **Minimum Steiner Tree Problem in Graphs** (NP-complete).
* **Algorithm:** We implement the **Kou-Markowsky-Berman (KMB) 2-approximation algorithm**, which runs in $O(k \cdot |V|^2)$ time:
  1. Construct metric closure over the terminal nodes.
  2. Compute the Minimum Spanning Tree (MST) of the metric closure.
  3. Replace MST edges with the shortest paths in the original graph.
  4. Prune redundant non-terminal leaves.
  5. Traverse from the optimal root table (fact table heuristic) using BFS to output an exact, ordered `JOIN ... ON` sequence.

---

## 3. AST-Based Deterministic Safety Gateway

### 3.1 Why Regex Fails
Regex-based SQL validation is fundamentally flawed. Adversarial inputs bypass string matching via inline comments (`/* comment */ DROP TABLE`), hex encoding, or subqueries (`WITH cte AS (DELETE ...) SELECT *`).

### 3.2 Abstract Syntax Tree (AST) Traversal with `sqlglot`
`schema-compass` uses compiler theory via `sqlglot`:
* **Node Whitelist:** The root expression MUST be a `Select`.
* **Node Blacklist:** Any node of type `Insert`, `Update`, `Delete`, `Drop`, `Alter`, `Truncate`, `Execute`, or `Command` anywhere in the AST raises an immediate `ASTSecurityViolation`.
* **Deterministic AST Rewriter:**
  * Injects `TOP <N>` (T-SQL) or `LIMIT <N>` (Postgres/DuckDB) if missing.
  * Injects `WITH (NOLOCK)` on SQL Server to prevent transaction locking in operational environments.
  * Rejects unconstrained Cartesian products (`CROSS JOIN` without filter).

---

## 4. Empirical Software Engineering Standards

Following the methodology of **Madeyski & Kitchenham** on reproducible empirical software engineering:
1. **Reproducibility & Environment:** The computational environment is part of the system artifact. Managed strictly via `uv` with locked dependencies (`uv.lock`) and explicit `pyproject.toml`.
2. **The Iron Law of TDD (`obra/superpowers` & Hermes standard):**
   * *No production code without a failing test first.*
   * Red $\rightarrow$ Green $\rightarrow$ Refactor in vertical tracer-bullet slices.
3. **Pragmatic Architecture:**
   * Favor `Function` $\rightarrow$ `Dataclass / Pydantic` $\rightarrow$ `Module` over over-engineered AbstractFactories, DI containers, and deep inheritance trees.
4. **Progressive Disclosure:**
   * MCP tools provide knowledge in tiers (`search_catalog` $\rightarrow$ `get_table_contract` $\rightarrow$ `get_join_tree`) to prevent context saturation.

---

## 5. Dimensional Modeling Heuristics (Ralph Kimball)

Automated classification of tables in DW environments:
* **Fact Tables:** Characterized by high row count, multiple outgoing foreign keys, numerical additive metrics, and references to date dimensions.
* **Dimension Tables:** Characterized by lower row count, primary surrogate keys, high ratio of descriptive text columns, and presence of SCD tracking columns (`valid_from`, `valid_to`, `is_current`).
