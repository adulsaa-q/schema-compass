from collections.abc import Sequence

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError


class ASTSecurityViolation(Exception):
    """Raised when a query attempts prohibited DDL/DML, multi-statement injection, or dangerous operations."""


PROHIBITED_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Create,
    exp.Merge,
    exp.Command,
    exp.Into,
    exp.Execute,
    exp.Grant,
    exp.Revoke,
    exp.Pragma,
    exp.Copy,
)

PROHIBITED_FUNCTIONS = {
    # SQL Server extended stored procedures and remote query providers
    "xp_cmdshell",
    "sp_oacreate",
    "sp_oamethod",
    "sp_oagetproperty",
    "sp_oasetproperty",
    "xp_dirtree",
    "xp_fileexist",
    "xp_regread",
    "xp_regwrite",
    "opendatasource",
    "openrowset",
    "openquery",
    # PostgreSQL administrative and file/network access functions
    "pg_read_file",
    "pg_write_file",
    "pg_read_binary_file",
    "dblink",
    "dblink_exec",
    # SQLite dynamic extension loading
    "load_extension",
}


import re

PII_COLUMN_PATTERNS = re.compile(
    r"(ssn|citizen|national_id|salary|wage|bonus|credit_card|card_num|cvv|password|passwd|secret|token|bank_acc|iban|passport)",
    re.IGNORECASE,
)


class ASTGuard:
    def validate(
        self,
        sql: str,
        dialect: str | None = None,
        allow_cartesian: bool = False,
        block_unaggregated_pii: bool = True,
        blocked_columns: set[str] | None = None,
        max_joins: int | None = 10,
        max_subquery_depth: int | None = 4,
    ) -> exp.Expression:
        # sqlglot can parse multiple statements; reject if empty or multi-statement
        try:
            statements: Sequence[exp.Expression | None] = sqlglot.parse(sql, read=dialect)
        except ParseError as e:
            raise ASTSecurityViolation(f"SQL parse error: {e}") from e

        valid_stmts = [s for s in statements if s is not None]
        if len(valid_stmts) != 1:
            raise ASTSecurityViolation(
                f"Expected exactly 1 statement, found {len(valid_stmts)}. Multi-statement execution blocked."
            )

        stmt = valid_stmts[0]

        # root expression must be a read query (Select, Union, etc.)
        if not isinstance(stmt, exp.Query):
            raise ASTSecurityViolation(
                f"Prohibited statement type: {stmt.key.upper() if hasattr(stmt, 'key') else type(stmt).__name__}. Only SELECT queries are permitted."
            )

        # scan full AST for any prohibited DDL/DML node (including in CTEs or subqueries)
        for prohibited in PROHIBITED_NODES:
            found = stmt.find(prohibited)
            if found is not None:
                raise ASTSecurityViolation(
                    f"Prohibited node detected in AST: {prohibited.__name__} ({found.sql()[:50]})"
                )

        # scan for dangerous functions / procedures / remote providers
        for func in stmt.find_all(exp.Func, exp.Anonymous):
            func_name = (func.name or func.sql_name() or "").lower()
            if func_name in PROHIBITED_FUNCTIONS or func_name.startswith(("xp_", "sp_oa")):
                raise ASTSecurityViolation(
                    f"Prohibited function or procedure detected: {func_name}"
                )

        for table in stmt.find_all(exp.Table):
            t_name = (table.name or "").lower()
            if t_name in PROHIBITED_FUNCTIONS or t_name.startswith(("xp_", "sp_oa")):
                raise ASTSecurityViolation(f"Prohibited table function detected: {t_name}")

        # Column-Level DLP and PII Protection
        if block_unaggregated_pii or blocked_columns:
            for col in stmt.find_all(exp.Column):
                col_name = col.name.lower()
                is_pii = bool(PII_COLUMN_PATTERNS.search(col_name))
                if blocked_columns and col_name in {c.lower() for c in blocked_columns}:
                    is_pii = True

                if is_pii and col.find_ancestor(exp.AggFunc) is None:
                    # check if column is projected inside an aggregate function (COUNT, SUM, AVG, MIN, MAX)
                    raise ASTSecurityViolation(
                        f"DLP Policy Violation: Direct selection of restricted/PII column '{col.name}' without aggregation is blocked."
                    )

        # Query Complexity Limits
        if max_joins is not None:
            for select_expr in stmt.find_all(exp.Select):
                joins = select_expr.args.get("joins") or []
                if len(joins) > max_joins:
                    raise ASTSecurityViolation(
                        f"Query complexity exceeded: Found {len(joins)} joins, maximum allowed is {max_joins}."
                    )

        if max_subquery_depth is not None:
            for select_expr in stmt.find_all(exp.Select):
                depth = 0
                curr = select_expr.parent
                while curr is not None:
                    if isinstance(curr, exp.Select):
                        depth += 1
                    curr = curr.parent
                if depth > max_subquery_depth:
                    raise ASTSecurityViolation(
                        f"Query complexity exceeded: Subquery nesting depth {depth} exceeds maximum {max_subquery_depth}."
                    )

        if not allow_cartesian:
            for select_expr in stmt.find_all(exp.Select):
                where_node = select_expr.args.get("where")
                where_tables: set[str] = set()
                if where_node is not None:
                    for col in where_node.find_all(exp.Column):
                        if col.table:
                            where_tables.add(col.table.lower())

                # Inspect only direct joins of this Select node to avoid subquery scope leaks
                joins = select_expr.args.get("joins") or []
                for join in joins:
                    has_on_or_using = bool(join.args.get("on") or join.args.get("using"))
                    is_cross = (
                        bool(join.kind and "CROSS" in join.kind.upper())
                        or join.args.get("kind") == "CROSS"
                    )

                    # Explicit CROSS JOIN without condition is always a Cartesian violation
                    if is_cross and not has_on_or_using:
                        raise ASTSecurityViolation(
                            f"Unconstrained Cartesian join detected: {join.sql()}. CROSS JOIN without condition blocked."
                        )

                    # Implicit comma join or unconstrained join must have participating table in WHERE
                    if not has_on_or_using:
                        table_name = (
                            join.this.alias_or_name.lower()
                            if hasattr(join.this, "alias_or_name")
                            else ""
                        )
                        if not table_name or table_name not in where_tables:
                            raise ASTSecurityViolation(
                                f"Unconstrained Cartesian join detected: {join.sql()}. Queries must specify ON, USING, or WHERE conditions."
                            )

        return stmt

    def rewrite(
        self,
        sql: str,
        dialect: str = "tsql",
        max_rows: int = 100,
        inject_nolock: bool = True,
        allow_cartesian: bool = False,
        block_unaggregated_pii: bool = True,
        blocked_columns: set[str] | None = None,
        max_joins: int | None = 10,
        max_subquery_depth: int | None = 4,
    ) -> str:
        # validates first to reject mutations, Cartesian joins, and DLP violations
        stmt = self.validate(
            sql,
            dialect=dialect,
            allow_cartesian=allow_cartesian,
            block_unaggregated_pii=block_unaggregated_pii,
            blocked_columns=blocked_columns,
            max_joins=max_joins,
            max_subquery_depth=max_subquery_depth,
        )

        # enforce positive integer row limit
        max_rows = max(1, max_rows)

        # clone AST to avoid modifying input
        ast = stmt.copy()

        # clamp or inject row limit on the root query
        limit_node = ast.args.get("limit")
        if limit_node is not None:
            expr = limit_node.expression or limit_node.args.get("count")
            if isinstance(expr, exp.Paren):
                expr = expr.this
            try:
                curr_limit = int(str(expr))
                if curr_limit > max_rows:
                    ast = ast.limit(max_rows)
            except (ValueError, TypeError):
                ast = ast.limit(max_rows)
        else:
            ast = ast.limit(max_rows)

        # for SQL Server, inject WITH (NOLOCK) on physical tables
        if dialect.lower() in ("tsql", "mssql", "sqlserver") and inject_nolock:
            cte_names = {cte.alias_or_name.lower() for cte in ast.find_all(exp.CTE)}
            for table in ast.find_all(exp.Table):
                # Only physical named tables receive hints; skip table variables (@var), TVFs, and CTEs
                if not isinstance(table.this, exp.Identifier):
                    continue
                tbl_name = table.name.lower()
                if tbl_name.startswith("@") or tbl_name in cte_names:
                    continue
                if not table.args.get("hints"):
                    table.set("hints", [exp.WithTableHint(expressions=[exp.var("NOLOCK")])])

        return ast.sql(dialect=dialect)
