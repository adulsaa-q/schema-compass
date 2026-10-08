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


# --- third round: join conditions that constrain nothing, file-reading table names, locks ----

FAKE_JOIN_CONDITIONS = [
    ("postgres", "SELECT * FROM orders a, orders b WHERE a.id = b.id OR 1 = 1"),
    ("postgres", "SELECT * FROM orders a, orders b WHERE NOT (a.id = b.id)"),
    ("postgres", "SELECT * FROM orders a, orders b WHERE a.id = b.id OR a.x = 1"),
    (
        "postgres",
        "SELECT * FROM orders a, orders b WHERE EXISTS (SELECT 1 FROM c WHERE a.id = b.id)",
    ),
    ("postgres", "SELECT * FROM orders a, orders b WHERE a.id <> b.id"),
    ("postgres", "SELECT * FROM orders a JOIN orders b ON 1 = 1"),
    ("postgres", "SELECT * FROM orders a JOIN orders b ON TRUE"),
    ("tsql", "SELECT * FROM orders a JOIN orders b ON a.id = a.id"),
    ("tsql", "SELECT * FROM orders a JOIN orders b ON 1 = 1 OR a.id = b.id"),
    ("tsql", "SELECT * FROM orders a LEFT JOIN orders b ON a.id = b.id OR 1 = 1"),
    ("postgres", "SELECT * FROM orders a FULL OUTER JOIN orders b ON a.id > 0"),
    ("postgres", "SELECT * FROM orders a JOIN orders b ON a.id IS NOT NULL"),
    ("postgres", "SELECT * FROM orders a JOIN orders b ON a.x = 1"),
    ("postgres", "SELECT * FROM orders a JOIN orders b ON b.x = 1 AND a.y = 2"),
]

REAL_JOIN_CONDITIONS = [
    ("postgres", "SELECT * FROM orders a JOIN orders b ON a.id = b.id"),
    ("postgres", "SELECT * FROM orders a JOIN orders b USING (id)"),
    ("postgres", "SELECT * FROM orders a, orders b WHERE a.id = b.id"),
    ("postgres", "SELECT * FROM orders a, orders b WHERE a.id = b.id AND a.x > 1"),
    ("postgres", "SELECT * FROM orders a JOIN orders b ON a.id = b.id AND b.x = 1"),
    ("postgres", "SELECT * FROM orders a JOIN orders b ON (a.id = b.id OR a.alt = b.id)"),
    ("postgres", "SELECT * FROM orders a LEFT JOIN orders b ON b.id = a.id WHERE b.id IS NULL"),
    ("tsql", "SELECT * FROM orders o JOIN customers c ON o.customer_id = c.customer_id"),
    ("tsql", "SELECT * FROM a JOIN b ON a.k = b.k JOIN c ON c.k = b.k"),
    ("tsql", "SELECT * FROM a, b, c WHERE a.k = b.k AND b.k = c.k"),
    ("sqlite", "SELECT * FROM a JOIN b ON customer_id = id"),  # unqualified columns get the benefit
    ("postgres", "SELECT * FROM a JOIN b ON a.k IS NOT DISTINCT FROM b.k"),
]


@pytest.mark.parametrize(("dialect", "sql"), FAKE_JOIN_CONDITIONS)
def test_join_condition_that_constrains_nothing_is_a_cartesian_join(
    guard: ASTGuard, dialect: str, sql: str
) -> None:
    with pytest.raises(ASTSecurityViolation, match="Cartesian"):
        guard.validate(sql, dialect=dialect)


@pytest.mark.parametrize(("dialect", "sql"), REAL_JOIN_CONDITIONS)
def test_real_join_condition_is_allowed(guard: ASTGuard, dialect: str, sql: str) -> None:
    guard.validate(sql, dialect=dialect)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM '/etc/passwd'",
        "SELECT * FROM 'C:/secret/data.csv'",
        r"SELECT * FROM 'C:\secret\data.csv'",
        'SELECT * FROM "data.parquet"',
        "SELECT * FROM 'events.json'",
        "SELECT * FROM 'https://example.com/x.csv'",
        r"SELECT * FROM 'C:\secret\data'",  # backslash only, no extension
    ],
)
def test_file_paths_used_as_table_names_are_blocked(guard: ASTGuard, sql: str) -> None:
    with pytest.raises(ASTSecurityViolation):
        guard.validate(sql, dialect="duckdb")


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("postgres", "SELECT * FROM orders FOR UPDATE"),
        ("postgres", "SELECT * FROM orders FOR SHARE NOWAIT"),
        ("mysql", "SELECT * FROM orders FOR UPDATE"),
        ("mysql", "SELECT * FROM orders LOCK IN SHARE MODE"),
    ],
)
def test_row_locking_clauses_are_blocked(guard: ASTGuard, dialect: str, sql: str) -> None:
    with pytest.raises(ASTSecurityViolation):
        guard.validate(sql, dialect=dialect)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM dba_users",
        "SELECT * FROM v$session",
        "SELECT * FROM sys.user$",
        "SELECT * FROM snowflake.account_usage.login_history",
    ],
)
def test_other_vendor_system_views_are_blocked(guard: ASTGuard, sql: str) -> None:
    dialect = "snowflake" if sql.startswith("SELECT * FROM snowflake") else "oracle"
    with pytest.raises(ASTSecurityViolation):
        guard.validate(sql, dialect=dialect)


def test_user_tables_that_resemble_system_names_still_work(guard: ASTGuard) -> None:
    for sql in ("SELECT * FROM all_orders", "SELECT * FROM user_events", "SELECT * FROM data_csv"):
        guard.validate(sql, dialect="postgres")


@pytest.mark.parametrize(
    ("dialect", "sql"),
    [
        ("tsql", "SELECT * FROM orders /* a /* b */ ; DROP TABLE x */ WHERE id = 1 -- tail"),
        ("postgres", "SELECT * FROM orders /* a /* b */ ; DROP TABLE x */ WHERE id = 1 -- tail"),
        ("mysql", "SELECT * FROM orders /* a */ WHERE id = 1 -- tail"),
        ("mysql", "SELECT * FROM orders /*!50000 WHERE id = 1 */"),
        ("sqlite", "SELECT * FROM orders /* a */ WHERE id = 1 -- tail"),
    ],
)
def test_rewritten_sql_carries_no_comments(guard: ASTGuard, dialect: str, sql: str) -> None:
    out = guard.rewrite(sql, dialect=dialect)
    assert "/*" not in out and "--" not in out and "DROP" not in out


def test_comment_nesting_that_the_dialect_does_not_support_is_rejected(guard: ASTGuard) -> None:
    with pytest.raises(ASTSecurityViolation):
        guard.rewrite("SELECT * FROM orders /* a /* b */ ; DROP TABLE x */", dialect="mysql")


# --- fourth round: equalities that mention both tables but cancel out ------------------------

J = "SELECT * FROM orders a JOIN orders b ON "

TAUTOLOGIES = [
    ("postgres", J + "a.id - a.id = b.id - b.id"),
    ("postgres", J + "a.id * 0 = b.id * 0"),
    ("postgres", J + "a.id = CASE WHEN 1 = 1 THEN a.id ELSE b.id END"),
    ("postgres", J + "a.id + b.id = a.id + b.id"),
    ("postgres", J + "COALESCE(a.id, b.id) = COALESCE(a.id, b.id)"),
    ("postgres", J + "a.id = a.id + b.id - b.id"),
    ("postgres", J + "a.id = ANY (SELECT b.id)"),
    ("postgres", J + "a.id = (SELECT MAX(id) FROM orders)"),
    ("postgres", J + "a.id = b.id OR TRUE"),
    ("postgres", J + "a.id = b.id OR 1 < 2"),
    ("postgres", J + "a.id % 1 = b.id % 1"),
    ("tsql", J + "a.id = b.id OR 'x' = 'x'"),
    ("tsql", "SELECT * FROM orders a JOIN orders b ON id - id = idx - idx"),
    ("postgres", "SELECT * FROM orders a, orders b WHERE a.id - a.id = b.id - b.id"),
    ("postgres", "SELECT * FROM orders a, orders b WHERE a.id = b.id OR TRUE"),
]

GENUINE_JOINS = [
    ("postgres", J + "UPPER(a.k) = UPPER(b.k)"),
    ("postgres", J + "b.ym = a.year * 100 + a.month"),
    ("postgres", J + "a.k = b.k AND a.s <> b.s"),
    ("postgres", J + "a.d BETWEEN b.s AND b.e AND a.k = b.k"),
    ("postgres", J + "a.k = b.k AND TRUE"),
    ("postgres", J + "CAST(a.k AS TEXT) = b.k_text"),
    ("postgres", J + "b.k = COALESCE(a.k, 0)"),
    ("tsql", J + "a.k = b.k AND a.k > 0"),
    ("tsql", "SELECT * FROM a JOIN b ON a.k = b.k JOIN c ON c.k = a.k AND c.j = b.j"),
]


@pytest.mark.parametrize(("dialect", "sql"), TAUTOLOGIES)
def test_self_cancelling_condition_is_still_a_cartesian_join(
    guard: ASTGuard, dialect: str, sql: str
) -> None:
    with pytest.raises(ASTSecurityViolation, match="Cartesian"):
        guard.validate(sql, dialect=dialect)


@pytest.mark.parametrize(("dialect", "sql"), GENUINE_JOINS)
def test_genuine_join_conditions_are_not_collateral_damage(
    guard: ASTGuard, dialect: str, sql: str
) -> None:
    guard.validate(sql, dialect=dialect)


@pytest.mark.anyio
async def test_every_join_tree_the_server_builds_passes_its_own_guard(guard: ASTGuard) -> None:
    import itertools

    from schema_compass.server import create_server
    from tests.fixtures.sample_schema import SAMPLE_CONTRACTS

    server = create_server(contracts=SAMPLE_CONTRACTS)
    names = [c.name for c in SAMPLE_CONTRACTS]
    checked = 0
    for size in (2, 3):
        for combo in itertools.combinations(names, size):
            reply = await server.call_tool("get_join_tree", {"tables": list(combo)})
            text = reply.content[0].text
            if "FROM" not in text:
                continue  # tables with no join path have no tree to check
            sql = "SELECT * " + text.replace("```sql", "").replace("```", "").strip()
            guard.validate(sql, dialect="tsql")
            checked += 1
    assert checked > 10
