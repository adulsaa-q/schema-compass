"""Regression tests for bypasses found by probing the guard with real dialect syntax."""

import pytest

from schema_compass.safety.ast_guard import ASTGuard, ASTSecurityViolation

BLOCKED = [
    # PostgreSQL: file system, large objects, nested SQL in strings, state-changing functions
    ("postgres", "SELECT pg_ls_dir('/')"),
    ("postgres", "SELECT * FROM pg_ls_dir('/')"),
    ("postgres", "SELECT lo_import('/etc/passwd')"),
    ("postgres", "SELECT query_to_xml('select * from pg_shadow', true, true, '')"),
    ("postgres", "SELECT nextval('orders_id_seq')"),
    ("postgres", "SELECT pg_advisory_lock(1)"),
    ("postgres", "SELECT pg_notify('c', 'x')"),
    # system catalogs that hold credentials and server configuration
    ("postgres", "SELECT * FROM pg_shadow"),
    ("postgres", "SELECT * FROM pg_catalog.pg_user"),
    ("tsql", "SELECT name FROM sys.sql_logins"),
    ("tsql", "SELECT * FROM master..sysdatabases"),
    ("tsql", "SELECT * FROM [MyDb].[sys].[objects]"),
    ("tsql", "SELECT * FROM syslogins"),
    ("sqlite", "SELECT * FROM sqlite_master"),
    ("sqlite", "SELECT * FROM main.sqlite_schema"),
    ("mysql", "SELECT * FROM mysql.user"),
    # T-SQL: functions outside the allowlist, lock-taking hints, unbounded recursion
    ("tsql", "SELECT * FROM fn_get_audit_file('x', NULL, NULL)"),
    ("tsql", "SELECT * FROM dbo.my_udf(1)"),
    ("tsql", "SELECT * FROM orders WITH (TABLOCKX)"),
    ("tsql", "SELECT * FROM orders WITH (UPDLOCK, HOLDLOCK)"),
    ("tsql", "SELECT * FROM orders WITH (NOLOCK, XLOCK)"),
    ("tsql", "SELECT * FROM orders OPTION (MAXRECURSION 0)"),
    (
        "tsql",
        "WITH r AS (SELECT 1 n UNION ALL SELECT n + 1 FROM r) SELECT * FROM r",
    ),
    # SQLite / MySQL / DuckDB: memory bombs, extension loading, file reads
    ("sqlite", "SELECT zeroblob(1000000000)"),
    ("sqlite", "SELECT randomblob(1000000000)"),
    ("sqlite", "SELECT load_extension('x')"),
    (
        "sqlite",
        "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT * FROM r",
    ),
    ("mysql", "SELECT LOAD_FILE('/etc/passwd')"),
    ("duckdb", "SELECT * FROM read_csv('/etc/passwd')"),
    ("duckdb", "SELECT * FROM read_parquet('/data/x.parquet')"),
]

ALLOWED = [
    ("tsql", "SELECT COUNT(*), SUM(total), AVG(total) FROM invoice GROUP BY customer_id"),
    ("tsql", "SELECT ISNULL(a, 0), DATEADD(day, 1, d), DATEDIFF(day, d, e), LEN(a) FROM t"),
    ("tsql", "SELECT CAST(a AS INT), TRY_CAST(a AS INT), CONVERT(VARCHAR(10), a) FROM t"),
    ("tsql", "SELECT * FROM orders WITH (NOLOCK)"),
    ("tsql", "SELECT * FROM orders WITH (READUNCOMMITTED)"),
    ("tsql", "SELECT * FROM orders WITH (NOLOCK, INDEX(ix_orders_date))"),
    ("tsql", "SELECT * FROM orders OPTION (MAXRECURSION 50)"),
    ("tsql", "SELECT * FROM orders OPTION (RECOMPILE)"),
    ("tsql", "SELECT value FROM STRING_SPLIT('a,b,c', ',')"),
    ("tsql", "WITH c AS (SELECT 1 AS n) SELECT * FROM c"),
    ("postgres", "SELECT DATE_PART('year', d), DATE_TRUNC('month', d), NOW() FROM t"),
    ("postgres", "SELECT ROW_NUMBER() OVER (PARTITION BY a ORDER BY b) FROM t"),
    ("postgres", "SELECT * FROM information_schema.columns"),
    ("postgres", "SELECT COALESCE(a, 'x'), UPPER(b), SUBSTRING(c FROM 1 FOR 2) FROM t"),
    ("sqlite", "SELECT strftime('%Y', d), IFNULL(a, 1), TYPEOF(a), JSON_EXTRACT(j, '$.x') FROM t"),
    ("sqlite", "SELECT * FROM t, json_each(t.j)"),
    ("mysql", "SELECT DATE_FORMAT(d, '%Y'), GROUP_CONCAT(a), IFNULL(b, 0) FROM t"),
    ("tsql", "SELECT * FROM orders;"),
    ("tsql", "SELECT * FROM orders; --"),
    ("tsql", "SELECT * FROM orders; /* trailing note */"),
]


@pytest.fixture
def guard() -> ASTGuard:
    return ASTGuard()


@pytest.mark.parametrize(("dialect", "sql"), BLOCKED)
def test_dangerous_query_is_blocked(guard: ASTGuard, dialect: str, sql: str) -> None:
    with pytest.raises(ASTSecurityViolation):
        guard.validate(sql, dialect=dialect)


@pytest.mark.parametrize(("dialect", "sql"), ALLOWED)
def test_ordinary_query_is_allowed(guard: ASTGuard, dialect: str, sql: str) -> None:
    guard.validate(sql, dialect=dialect)


def test_semicolon_then_real_statement_is_still_blocked(guard: ASTGuard) -> None:
    with pytest.raises(ASTSecurityViolation):
        guard.validate("SELECT 1; DROP TABLE orders; --", dialect="tsql")


def test_lock_hint_cannot_survive_rewrite(guard: ASTGuard) -> None:
    out = guard.rewrite("SELECT * FROM orders WITH (NOLOCK)", dialect="tsql")
    assert "NOLOCK" in out
    with pytest.raises(ASTSecurityViolation):
        guard.rewrite("SELECT * FROM orders WITH (TABLOCKX)", dialect="tsql")


def test_extra_allowed_function_can_be_enabled() -> None:
    sql = "SELECT * FROM dbo.my_udf(1)"
    with pytest.raises(ASTSecurityViolation):
        ASTGuard().validate(sql, dialect="tsql")
    ASTGuard(extra_allowed_functions={"MY_UDF"}).validate(sql, dialect="tsql")


def test_extra_allowed_functions_never_unlock_hard_denied_ones() -> None:
    guard = ASTGuard(extra_allowed_functions={"xp_cmdshell", "pg_read_file", "load_extension"})
    for dialect, sql in [
        ("tsql", "SELECT * FROM xp_cmdshell('dir')"),
        ("postgres", "SELECT pg_read_file('/etc/passwd')"),
        ("sqlite", "SELECT load_extension('x')"),
    ]:
        with pytest.raises(ASTSecurityViolation):
            guard.validate(sql, dialect=dialect)


def test_recursive_cte_can_be_enabled() -> None:
    sql = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 5) SELECT * FROM r"
    with pytest.raises(ASTSecurityViolation):
        ASTGuard().validate(sql, dialect="sqlite")
    ASTGuard(allow_recursive_cte=True).validate(sql, dialect="sqlite")


def test_maxrecursion_zero_blocked_even_when_recursion_enabled() -> None:
    guard = ASTGuard(allow_recursive_cte=True)
    with pytest.raises(ASTSecurityViolation):
        guard.validate(
            "WITH r AS (SELECT 1 n UNION ALL SELECT n + 1 FROM r) SELECT * FROM r OPTION (MAXRECURSION 0)",
            dialect="tsql",
        )


def test_system_catalogs_can_be_enabled() -> None:
    sql = "SELECT name FROM sys.objects"
    with pytest.raises(ASTSecurityViolation):
        ASTGuard().validate(sql, dialect="tsql")
    ASTGuard(allow_system_catalogs=True).validate(sql, dialect="tsql")


def test_user_table_with_similar_name_is_not_flagged(guard: ASTGuard) -> None:
    guard.validate("SELECT * FROM system_events", dialect="tsql")
    guard.validate("SELECT * FROM sysadmin_notes", dialect="tsql")


# --- found by a second round of probing (review findings) ---------------------------------

CARTESIAN_VIA_FAKE_CORRELATION = [
    ("sqlite", "SELECT * FROM orders o, (SELECT * FROM orders b WHERE o.order_id IS NOT NULL) x"),
    (
        "postgres",
        "SELECT * FROM orders o CROSS JOIN LATERAL (SELECT * FROM orders b WHERE o.order_id > 0) x",
    ),
    ("tsql", "SELECT * FROM orders o CROSS APPLY (SELECT * FROM orders b WHERE o.order_id > 0) x"),
]


@pytest.mark.parametrize(("dialect", "sql"), CARTESIAN_VIA_FAKE_CORRELATION)
def test_referencing_an_outer_table_does_not_excuse_a_cartesian_join(
    guard: ASTGuard, dialect: str, sql: str
) -> None:
    with pytest.raises(ASTSecurityViolation):
        guard.validate(sql, dialect=dialect)


def test_table_function_over_an_earlier_table_is_still_allowed(guard: ASTGuard) -> None:
    guard.validate("SELECT * FROM t, json_each(t.j)", dialect="sqlite")


@pytest.mark.parametrize("literal", ["0", "00", "000", "0x0", "0X00", "-1", "abc", "@limit"])
def test_maxrecursion_without_a_real_bound_is_blocked(literal: str) -> None:
    sql = (
        "WITH r AS (SELECT 1 n UNION ALL SELECT n + 1 FROM r) "
        f"SELECT * FROM r OPTION (MAXRECURSION {literal})"
    )
    with pytest.raises(ASTSecurityViolation):
        ASTGuard(allow_recursive_cte=True).validate(sql, dialect="tsql")


def test_maxrecursion_with_a_bound_is_allowed_when_recursion_is_enabled() -> None:
    sql = (
        "WITH r AS (SELECT 1 n UNION ALL SELECT n + 1 FROM r WHERE n < 5) "
        "SELECT * FROM r OPTION (MAXRECURSION 100)"
    )
    ASTGuard(allow_recursive_cte=True).validate(sql, dialect="tsql")


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("tsql", "SELECT * FROM srv.master.sys.sql_logins"),
        ("tsql", "SELECT * FROM linkedsrv.salesdb.dbo.orders"),
        ("tsql", "SELECT * FROM [srv].[master].[sys].[sql_logins]"),
    ],
)
def test_four_part_names_are_blocked_as_remote_server_access(
    guard: ASTGuard, dialect: str, sql: str
) -> None:
    with pytest.raises(ASTSecurityViolation):
        guard.validate(sql, dialect=dialect)


def test_three_part_names_to_user_data_still_work(guard: ASTGuard) -> None:
    guard.validate("SELECT * FROM salesdb.dbo.orders", dialect="tsql")
    guard.validate(
        "SELECT * FROM model", dialect="tsql"
    )  # a user table that happens to be named model


def test_mysql_executable_comment_is_neutralised_in_the_rewritten_sql(guard: ASTGuard) -> None:
    out = guard.rewrite("SELECT 1 /*!50000 UNION SELECT user FROM mysql.user */", dialect="mysql")
    assert "/*!" not in out
