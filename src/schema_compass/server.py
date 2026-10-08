import logging

from mcp.server.mcpserver import MCPServer
from sqlglot.errors import ParseError

from schema_compass import __version__
from schema_compass.graph.schema_graph import SchemaGraph
from schema_compass.graph.steiner_solver import SteinerJoinSolver
from schema_compass.models import DisconnectedGraphError, TableContract
from schema_compass.profiler.contract import format_contract
from schema_compass.profiler.erd import generate_mermaid_erd
from schema_compass.safety.ast_guard import ASTGuard, ASTSecurityViolation
from schema_compass.safety.audit import AuditLogger

logger = logging.getLogger(__name__)


def create_server(contracts: list[TableContract] | None = None) -> MCPServer:
    server = MCPServer(
        name="schema-compass",
        description="Database topology navigator and AST safety gateway",
        version=__version__,
    )

    loaded_contracts = contracts or []
    contracts_by_name: dict[str, TableContract] = {c.name.lower(): c for c in loaded_contracts}
    for c in loaded_contracts:
        contracts_by_name[c.full_name.lower()] = c

    graph = SchemaGraph()
    if loaded_contracts:
        graph.load_contracts(loaded_contracts)

    solver = SteinerJoinSolver(graph)
    guard = ASTGuard()

    @server.tool(
        name="search_catalog",
        description="Search database catalog for tables, views, and columns matching keywords",
    )
    def search_catalog(query: str, top_k: int = 5) -> str:
        # rank tables by keyword matches in table name, description, and column attributes
        q = query.strip().lower()
        if not q:
            return "No query provided."

        matches: list[tuple[float, TableContract, list[str]]] = []
        for contract in loaded_contracts:
            score = 0.0
            matched_cols: list[str] = []
            if q in contract.name.lower():
                score += 10.0
            if contract.description and q in contract.description.lower():
                score += 3.0
            for col in contract.columns:
                if q in col.name.lower():
                    score += 5.0
                    matched_cols.append(col.name)
                elif col.description and q in col.description.lower():
                    score += 2.0
                    matched_cols.append(col.name)

            if score > 0:
                matches.append((score, contract, matched_cols))

        matches.sort(key=lambda x: x[0], reverse=True)
        top_matches = matches[:top_k]

        if not top_matches:
            return f"No catalog matches found for '{query}'."

        lines = [f"Found {len(top_matches)} catalog matches for '{query}':"]
        for _, c, cols in top_matches:
            col_hint = f" (matched columns: {', '.join(cols)})" if cols else ""
            lines.append(f"- **{c.full_name}** [{c.role} | {c.row_count:,} rows]{col_hint}")
        return "\n".join(lines)

    @server.tool(
        name="get_join_tree",
        description="Computes minimal Steiner join path connecting requested tables and returns SQL FROM ... JOIN clause",
    )
    def get_join_tree(tables: list[str]) -> str:
        # minimum Steiner tree across terminal tables
        if len(tables) < 2:
            return "At least 2 tables are required to calculate a join tree."
        try:
            tree = solver.solve(tables)
            return tree.to_sql_from_clause()
        except (DisconnectedGraphError, KeyError, ValueError) as e:
            return f"Failed to compute join tree: {e}"

    @server.tool(
        name="get_table_contract",
        description="Returns Minimal Effective Context (MEC) schema contract (< 200 tokens) with column types, keys, and samples",
    )
    def get_table_contract(table_name: str, mode: str = "compact") -> str:
        tname = table_name.strip().lower()
        contract = contracts_by_name.get(tname)
        if not contract:
            return f"Table '{table_name}' not found in catalog."
        return format_contract(contract, mode="full" if mode.lower() == "full" else "compact")

    @server.tool(
        name="explain_metric",
        description="Returns business definition, calculation formula, and upstream column lineage for standard or documented metrics",
    )
    def explain_metric(metric_name: str) -> str:
        # look for columns matching metric name
        q = metric_name.strip().lower()
        found: list[str] = []
        for contract in loaded_contracts:
            for col in contract.columns:
                if q in col.name.lower():
                    found.append(
                        f"- Table: {contract.full_name}, Column: {col.name} ({col.data_type})"
                    )
        if not found:
            return f"No documented metric or column found matching '{metric_name}'."
        return f"Metric definitions for '{metric_name}':\n" + "\n".join(found)

    audit_logger = AuditLogger()

    @server.tool(
        name="get_schema_diagram",
        description="Generates an Entity-Relationship (ER) diagram in Mermaid format for the requested tables or entire schema",
    )
    def get_schema_diagram(tables: list[str] | None = None) -> str:
        if not loaded_contracts:
            return "No tables in catalog to generate diagram."

        if tables:
            selected_names = {t.strip().lower() for t in tables}
            filtered: list[TableContract] = []
            for c in loaded_contracts:
                if c.name.lower() in selected_names or c.full_name.lower() in selected_names:
                    filtered.append(c)
                else:
                    for rel in c.relationships:
                        if rel.target_table.lower() in selected_names:
                            filtered.append(c)
                            break
            target_tables = filtered or loaded_contracts
        else:
            target_tables = loaded_contracts

        erd_code = generate_mermaid_erd(target_tables)
        return f"```mermaid\n{erd_code}\n```"

    @server.tool(
        name="execute_safe_query",
        description="Validates SQL via AST traversal, enforces read-only execution, DLP checks, and clamps row limits (TOP/LIMIT)",
    )
    def execute_safe_query(sql: str, dialect: str = "tsql", max_rows: int = 100) -> str:
        logger.info("execute_safe_query called with dialect=%s, max_rows=%d", dialect, max_rows)
        try:
            rewritten_sql = guard.rewrite(sql, dialect=dialect, max_rows=max_rows)
            audit_logger.log_query(sql=sql, dialect=dialect, allowed=True, max_rows=max_rows)
            return f"Validated Safe SQL ({dialect}):\n{rewritten_sql}"
        except ASTSecurityViolation as e:
            logger.warning("execute_safe_query blocked by AST security policy: %s", e)
            audit_logger.log_query(
                sql=sql, dialect=dialect, allowed=False, reason=str(e), max_rows=max_rows
            )
            return f"Security violation: {e}"
        except (ParseError, ValueError, TypeError) as e:
            logger.warning("execute_safe_query validation failure: %s", e)
            audit_logger.log_query(
                sql=sql, dialect=dialect, allowed=False, reason=str(e), max_rows=max_rows
            )
            return f"Query validation error: {e}"

    return server


def load_contracts_from_source(source_type: str, path: str | None = None) -> list[TableContract]:
    import json
    import sqlite3
    from pathlib import Path

    from schema_compass.dialects.sqlite import SQLiteAdapter

    logger.info("Loading contracts from source_type=%s, path=%s", source_type, path)
    stype = source_type.lower()
    if stype == "json" and path:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Schema JSON file not found: {path}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [TableContract.model_validate(item) for item in data]

    if stype == "sqlite" and path:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"SQLite database file not found: {path}")
        conn = sqlite3.connect(str(p))
        try:
            adapter = SQLiteAdapter(conn)
            return adapter.extract_contracts()
        finally:
            conn.close()

    # default fallback to sample schema fixture
    from schema_compass.sample_schema import SAMPLE_CONTRACTS

    return SAMPLE_CONTRACTS


def main() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Schema-Compass MCP Server")
    parser.add_argument(
        "--source",
        choices=["sample", "sqlite", "json"],
        default=os.getenv("SCHEMA_COMPASS_SOURCE", "sample"),
        help="Schema source type: sample, sqlite, or json",
    )
    parser.add_argument(
        "--path",
        default=os.getenv("SCHEMA_COMPASS_PATH"),
        help="Path to sqlite .db file or pre-exported schema .json file",
    )
    args = parser.parse_args()

    contracts = load_contracts_from_source(args.source, args.path)
    server = create_server(contracts=contracts)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
