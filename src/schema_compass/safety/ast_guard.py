import logging
from collections.abc import Iterable

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from schema_compass.models import SchemaCompassError

logger = logging.getLogger(__name__)


class ASTSecurityViolation(SchemaCompassError):
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
    "sp_executesql",
    # PostgreSQL administrative, file/network access, and session alteration
    "pg_read_file",
    "pg_write_file",
    "pg_read_binary_file",
    "pg_sleep",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "dblink",
    "dblink_exec",
    "set_config",
    "current_setting",
    # MySQL / generic side-channel and DoS
    "sleep",
    "benchmark",
    "sys_exec",
    "sys_eval",
    # SQLite dynamic extension loading and memory exhaustion
    "load_extension",
    "randomblob",
}


# Functions that sqlglot does not model as typed nodes but that are ordinary, side-effect free
# SQL. Anything else that parses as an unknown ("anonymous") function is rejected, so a new
# dangerous function is blocked by default instead of passing until someone adds it to a deny-list.
# Typed functions (COUNT, COALESCE, CAST, ...) are standard SQL and are allowed, except the nodes below.
ALLOWED_ANONYMOUS_FUNCTIONS = frozenset(
    {
        "age",
        "binary_checksum",
        "bit_and",
        "bit_count",
        "bit_or",
        "bit_xor",
        "cardinality",
        "checksum",
        "checksum_agg",
        "choose",
        "count_big",
        "crc32",
        "datalength",
        "date_format",
        "date_part",
        "date_sub",
        "dateadd",
        "datename",
        "datepart",
        "datetime",
        "datetime2fromparts",
        "difference",
        "eomonth",
        "every",
        "format_date",
        "from_unixtime",
        "getdate",
        "hash",
        "if_null",
        "isdate",
        "isjson",
        "isnull",
        "isnumeric",
        "json_agg",
        "json_array",
        "json_array_elements",
        "json_array_length",
        "json_build_object",
        "json_each",
        "json_group_array",
        "json_group_object",
        "json_query",
        "json_tree",
        "json_valid",
        "json_value",
        "jsonb_agg",
        "jsonb_array_elements",
        "jsonb_extract_path",
        "julianday",
        "likely",
        "list_agg",
        "listagg",
        "make_date",
        "make_timestamp",
        "nchar",
        "newid",
        "now",
        "nullifzero",
        "octet_length",
        "openjson",
        "parse",
        "patindex",
        "printf",
        "regexp_matches",
        "row_to_json",
        "sha256",
        "stdevp",
        "strftime",
        "string_split",
        "sum_if",
        "sysdate",
        "sysdatetime",
        "time",
        "timestampadd",
        "to_date",
        "to_decimal",
        "to_json",
        "to_jsonb",
        "to_timestamp",
        "to_varchar",
        "total",
        "trunc",
        "try_parse",
        "try_to_date",
        "try_to_number",
        "unix_timestamp",
        "unlikely",
        "var",
        "weekday",
        "zeroifnull",
    }
)

# Typed sqlglot nodes that read files, call the network, or call hosted models.
PROHIBITED_FUNCTION_NODES = (
    exp.ReadCSV,
    exp.ReadParquet,
    exp.ToFile,
    exp.NetFunc,
    exp.AIGenerate,
    exp.GenerateEmbedding,
    exp.GenerateText,
    exp.GenerateBool,
    exp.GenerateInt,
    exp.GenerateDouble,
)

# Never unlocked by `extra_allowed_functions`: file/OS access, sleeps, and functions that
# change server state (sequences, advisory locks, notifications, large objects).
HARD_DENIED_FUNCTIONS = PROHIBITED_FUNCTIONS | {
    "nextval",
    "setval",
    "lastval",
    "pg_advisory_lock",
    "pg_advisory_xact_lock",
    "pg_try_advisory_lock",
    "pg_notify",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "lo_create",
    "lo_unlink",
    "query_to_xml",
    "load_file",
    "read_csv",
    "read_parquet",
}
HARD_DENIED_PREFIXES = ("xp_", "sp_oa", "lo_")

# Table hints that never take locks beyond a normal read.
ALLOWED_TABLE_HINTS = frozenset(
    {"nolock", "readuncommitted", "readcommitted", "index", "forceseek", "forcescan", "noexpand"}
)

SYSTEM_SCHEMAS = frozenset({"sys", "pg_catalog", "pg_toast", "mysql", "performance_schema"})
SYSTEM_DATABASES = frozenset({"master", "msdb", "tempdb", "model"})


import re

PII_COLUMN_PATTERNS = re.compile(
    r"(ssn|citizen|national_id|salary|wage|bonus|credit_card|card_num|cvv|password|passwd|secret|token|bank_acc|iban|passport)",
    re.IGNORECASE,
)

SENSITIVE_TABLE_PATTERNS = re.compile(
    r"(employee|user|payroll|salary|credential|auth|account)",
    re.IGNORECASE,
)


SYSTEM_TABLE_PATTERN = re.compile(
    r"^(pg_|sqlite_)|^sys(databases|logins|objects|columns|users|processes|servers|configures"
    r"|comments|xlogins|indexes|types)$",
    re.IGNORECASE,
)

MAX_NAME_PARTS = 3  # database.schema.table; more means a linked/remote server
MAX_RECURSION_LIMIT = 32_767  # SQL Server's own ceiling for OPTION (MAXRECURSION n)
MAX_SQL_LENGTH = 100_000  # 100 KB payload limit to prevent parser memory bombs


class ASTGuard:
    """Read-only SQL gatekeeper.

    Policy is fixed per instance:
      extra_allowed_functions: function names to allow beyond the built-in allowlist
        (e.g. your own UDFs). Hard-denied functions can never be unlocked this way.
      allow_recursive_cte: permit recursive CTEs (off by default: they can run unbounded).
      allow_system_catalogs: permit reads of sys.*, pg_catalog, sqlite_master and similar.
    """

    def __init__(
        self,
        extra_allowed_functions: Iterable[str] = (),
        allow_recursive_cte: bool = False,
        allow_system_catalogs: bool = False,
    ) -> None:
        self.extra_allowed_functions = frozenset(f.lower() for f in extra_allowed_functions)
        self.allow_recursive_cte = allow_recursive_cte
        self.allow_system_catalogs = allow_system_catalogs

    def validate(
        self,
        sql: str,
        dialect: str | None = None,
        allow_cartesian: bool = False,
        block_unaggregated_pii: bool = True,
        blocked_columns: set[str] | None = None,
        blocked_tables: set[str] | None = None,
        max_joins: int | None = 10,
        max_subquery_depth: int | None = 4,
    ) -> exp.Query:
        # Fail fast: reject oversized payloads before AST parsing
        if len(sql) > MAX_SQL_LENGTH:
            logger.warning("SQL payload exceeded maximum length: length=%d", len(sql))
            raise ASTSecurityViolation(
                f"SQL payload too large ({len(sql):,} chars). Maximum allowed is {MAX_SQL_LENGTH:,}."
            )

        # sqlglot can parse multiple statements; reject if empty or multi-statement
        logger.debug(
            "Validating query with dialect=%s, allow_cartesian=%s", dialect, allow_cartesian
        )
        try:
            statements = sqlglot.parse(sql, read=dialect)
        except ParseError as e:
            logger.warning("SQL parse error for query: %s", e)
            raise ASTSecurityViolation(f"SQL parse error: {e}") from e

        valid_stmts = [s for s in statements if s is not None and not isinstance(s, exp.Semicolon)]
        if len(valid_stmts) != 1:
            logger.warning("Multi-statement attempt detected: count=%d", len(valid_stmts))
            raise ASTSecurityViolation(
                f"Expected exactly 1 statement, found {len(valid_stmts)}. Multi-statement execution blocked."
            )

        stmt = valid_stmts[0]

        # root expression must be a read query (Select, Union, etc.)
        if not isinstance(stmt, exp.Query):
            logger.warning("Prohibited statement type attempted: %s", type(stmt).__name__)
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

        self._check_functions(stmt)
        self._check_tables(stmt)
        self._check_query_options(stmt)
        if not self.allow_recursive_cte:
            self._check_no_recursion(stmt)

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

        # Wildcard DLP Protection on sensitive tables
        # Wildcard DLP Protection on sensitive tables
        if blocked_tables:
            for select_expr in stmt.find_all(exp.Select):
                has_star = bool(list(select_expr.find_all(exp.Star)))
                if has_star:
                    direct_tables: set[str] = set()
                    from_node = select_expr.args.get("from") or select_expr.args.get("from_")
                    if from_node and from_node.this:
                        if hasattr(from_node.this, "name") and from_node.this.name:
                            direct_tables.add(from_node.this.name.lower())
                        if (
                            hasattr(from_node.this, "alias_or_name")
                            and from_node.this.alias_or_name
                        ):
                            direct_tables.add(from_node.this.alias_or_name.lower())
                    for join in select_expr.args.get("joins") or []:
                        if join.this:
                            if hasattr(join.this, "name") and join.this.name:
                                direct_tables.add(join.this.name.lower())
                            if hasattr(join.this, "alias_or_name") and join.this.alias_or_name:
                                direct_tables.add(join.this.alias_or_name.lower())

                    for tbl in direct_tables:
                        if tbl in {t.lower() for t in blocked_tables}:
                            raise ASTSecurityViolation(
                                f"DLP Policy Violation: Wildcard SELECT (*) on sensitive table '{tbl}' is blocked under DLP policy. Explicit column projection is required."
                            )

        if not allow_cartesian:
            for select_expr in stmt.find_all(exp.Select):
                where_node = select_expr.args.get("where")
                where_cross_pairs: set[frozenset[str]] = set()
                if where_node is not None:
                    for eq in where_node.find_all(exp.EQ):
                        left = eq.this
                        right = eq.expression
                        if (
                            isinstance(left, exp.Column)
                            and isinstance(right, exp.Column)
                            and left.table
                            and right.table
                        ):
                            t1 = left.table.lower()
                            t2 = right.table.lower()
                            if t1 != t2:
                                where_cross_pairs.add(frozenset([t1, t2]))

                # Inspect only direct joins of this Select node to avoid subquery scope leaks
                joins = select_expr.args.get("joins") or []
                for join in joins:
                    has_on_or_using = bool(join.args.get("on") or join.args.get("using"))
                    is_cross = (
                        bool(join.kind and "CROSS" in join.kind.upper())
                        or join.args.get("kind") == "CROSS"
                    )

                    # Explicit CROSS JOIN without condition is always a Cartesian violation
                    if (
                        is_cross
                        and not has_on_or_using
                        and not self._is_correlated(select_expr, join)
                    ):
                        raise ASTSecurityViolation(
                            f"Unconstrained Cartesian join detected: {join.sql()}. CROSS JOIN without condition blocked."
                        )

                    # A join whose right side reads an earlier table (json_each(t.j), LATERAL,
                    # CROSS APPLY) is correlated per row, not a Cartesian product.
                    if not has_on_or_using and self._is_correlated(select_expr, join):
                        continue

                    # Implicit comma join or unconstrained join must have equijoin connecting to another table
                    if not has_on_or_using:
                        table_name = (
                            join.this.alias_or_name.lower()
                            if hasattr(join.this, "alias_or_name")
                            else ""
                        )
                        is_linked = any(table_name in pair for pair in where_cross_pairs)
                        if not table_name or not is_linked:
                            raise ASTSecurityViolation(
                                f"Unconstrained Cartesian join detected: {join.sql()}. Comma join requires cross-table equijoin predicate in WHERE."
                            )

        return stmt

    def _check_functions(self, stmt: exp.Query) -> None:
        for node in stmt.find_all(exp.Func):
            if isinstance(node, PROHIBITED_FUNCTION_NODES):
                raise ASTSecurityViolation(
                    f"Prohibited function detected: {node.sql_name().lower()}"
                )
            if not isinstance(node, exp.Anonymous) or isinstance(node.parent, exp.WithTableHint):
                continue  # typed = standard SQL; hint items are vetted in _check_tables
            name = node.name.lower()
            if name in HARD_DENIED_FUNCTIONS or name.startswith(HARD_DENIED_PREFIXES):
                raise ASTSecurityViolation(f"Prohibited function or procedure detected: {name}")
            if name not in ALLOWED_ANONYMOUS_FUNCTIONS and name not in self.extra_allowed_functions:
                raise ASTSecurityViolation(
                    f"Function '{name}' is not on the allowlist. "
                    "Allow it explicitly (extra_allowed_functions) if it is safe."
                )

    def _check_tables(self, stmt: exp.Query) -> None:
        cte_names = {cte.alias_or_name.lower() for cte in stmt.find_all(exp.CTE)}
        for table in stmt.find_all(exp.Table):
            name = (table.name or "").lower()
            if name in HARD_DENIED_FUNCTIONS or name.startswith(HARD_DENIED_PREFIXES):
                raise ASTSecurityViolation(f"Prohibited table function detected: {name}")

            for hint in table.args.get("hints") or []:
                for item in getattr(hint, "expressions", None) or []:
                    hint_name = (item.name or "").lower()
                    if hint_name not in ALLOWED_TABLE_HINTS:
                        raise ASTSecurityViolation(
                            f"Table hint '{hint_name.upper()}' is blocked: it can take locks. "
                            "Only NOLOCK/READUNCOMMITTED and plain index hints are allowed."
                        )

            parts = [part.name.lower() for part in table.parts]
            if len(parts) > MAX_NAME_PARTS:
                raise ASTSecurityViolation(
                    f"Four-part name '{table.sql()[:60]}' (linked server access) is blocked."
                )
            if self.allow_system_catalogs or (name in cte_names and len(parts) == 1):
                continue
            qualifiers = parts[:-1]
            if any(
                q in SYSTEM_SCHEMAS or q in SYSTEM_DATABASES for q in qualifiers
            ) or SYSTEM_TABLE_PATTERN.search(name):
                raise ASTSecurityViolation(
                    f"Access to system catalog '{table.sql()[:60]}' is blocked "
                    "(it can expose credentials and server configuration)."
                )

    @staticmethod
    def _is_correlated(select: exp.Select, join: exp.Join) -> bool:
        """True for a table function fed by an earlier table, e.g. `FROM t, json_each(t.j)`.

        Its row count is bounded by the value in each row. Subqueries, LATERAL and APPLY are
        deliberately not excused: referencing an outer column once does not constrain the join.
        """
        target = join.this
        is_table_function = isinstance(target, exp.Unnest) or (
            isinstance(target, exp.Table) and isinstance(target.this, exp.Func)
        )
        if not is_table_function:
            return False
        from_node = select.args.get("from") or select.args.get("from_")
        earlier = [from_node.this] if from_node is not None and from_node.this else []
        for other in select.args.get("joins") or []:
            if other is join:
                break
            earlier.append(other.this)
        names = {e.alias_or_name.lower() for e in earlier if e is not None and e.alias_or_name}
        return any(col.table.lower() in names for col in target.find_all(exp.Column) if col.table)

    def _check_query_options(self, stmt: exp.Query) -> None:
        for option in stmt.find_all(exp.QueryOption):
            if (option.name or "").lower() != "maxrecursion":
                continue
            value = option.expression
            text = value.name if isinstance(value, exp.Literal) else ""
            if not (text.isdigit() and 1 <= int(text) <= MAX_RECURSION_LIMIT):
                raise ASTSecurityViolation(
                    f"OPTION (MAXRECURSION {option.expression.sql() if value else ''}) does not "
                    f"set a bound between 1 and {MAX_RECURSION_LIMIT}."
                )

    def _check_no_recursion(self, stmt: exp.Query) -> None:
        for with_ in stmt.find_all(exp.With):
            if with_.args.get("recursive"):
                raise ASTSecurityViolation(
                    "Recursive CTEs are blocked because they can run without bound."
                )
            for cte in with_.expressions:
                own_name = cte.alias_or_name.lower()
                if any(
                    t.name.lower() == own_name and not t.db for t in cte.this.find_all(exp.Table)
                ):
                    raise ASTSecurityViolation(
                        f"Recursive CTE '{own_name}' is blocked because it can run without bound."
                    )

    def rewrite(
        self,
        sql: str,
        dialect: str = "tsql",
        max_rows: int = 100,
        inject_nolock: bool = True,
        allow_cartesian: bool = False,
        block_unaggregated_pii: bool = True,
        blocked_columns: set[str] | None = None,
        blocked_tables: set[str] | None = None,
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
            blocked_tables=blocked_tables,
            max_joins=max_joins,
            max_subquery_depth=max_subquery_depth,
        )

        # enforce positive integer row limit
        max_rows = max(1, max_rows)

        # clone AST to avoid modifying input
        cloned = stmt.copy()
        ast: exp.Query = cloned if isinstance(cloned, exp.Query) else stmt

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
