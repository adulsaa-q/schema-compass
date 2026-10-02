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
)


class ASTGuard:
    def validate(
        self,
        sql: str,
        dialect: str | None = None,
        allow_cartesian: bool = False,
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

        if not allow_cartesian:
            for select_expr in stmt.find_all(exp.Select):
                has_where = select_expr.args.get("where") is not None
                for join in select_expr.find_all(exp.Join):
                    has_on_or_using = bool(join.args.get("on") or join.args.get("using"))
                    if not has_on_or_using and not has_where:
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
    ) -> str:
        # validates first to reject mutations and Cartesian joins
        stmt = self.validate(sql, dialect=dialect, allow_cartesian=allow_cartesian)

        # clone AST to avoid modifying input
        ast = stmt.copy()

        # clamp or inject row limit on the root query
        limit_node = ast.args.get("limit")
        if limit_node is not None:
            expr = limit_node.expression
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
                # CTE references and tables that already have hints must not get duplicate hints
                if table.name.lower() not in cte_names and not table.args.get("hints"):
                    table.set("hints", [exp.WithTableHint(expressions=[exp.var("NOLOCK")])])

        return ast.sql(dialect=dialect)
