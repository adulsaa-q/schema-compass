import pytest

from schema_compass.safety.ast_guard import ASTGuard, ASTSecurityViolation


@pytest.fixture
def guard() -> ASTGuard:
    return ASTGuard()


def test_valid_select_query(guard: ASTGuard) -> None:
    # simple select should pass without error
    sql = "SELECT id, name FROM users WHERE status = 'active'"
    guard.validate(sql)


def test_rejects_mutation_dml(guard: ASTGuard) -> None:
    mutations = [
        "INSERT INTO users (name) VALUES ('test')",
        "UPDATE users SET status = 'inactive' WHERE id = 1",
        "DELETE FROM users WHERE id = 1",
        "MERGE INTO target USING source ON target.id = source.id WHEN MATCHED THEN DELETE",
    ]
    for sql in mutations:
        with pytest.raises(ASTSecurityViolation):
            guard.validate(sql)


def test_rejects_ddl_statements(guard: ASTGuard) -> None:
    ddl_statements = [
        "DROP TABLE users",
        "TRUNCATE TABLE logs",
        "ALTER TABLE users ADD COLUMN age INT",
        "CREATE TABLE test (id INT)",
    ]
    for sql in ddl_statements:
        with pytest.raises(ASTSecurityViolation):
            guard.validate(sql)


def test_rejects_multi_statement_injection(guard: ASTGuard) -> None:
    sql = "SELECT id FROM users; DROP TABLE logs;"
    with pytest.raises(ASTSecurityViolation):
        guard.validate(sql)


def test_rejects_cte_mutation(guard: ASTGuard) -> None:
    # adversarial CTE hiding a DELETE statement
    sql = "WITH deleted AS (DELETE FROM users RETURNING *) SELECT * FROM deleted"
    with pytest.raises(ASTSecurityViolation):
        guard.validate(sql)


def test_rejects_select_into(guard: ASTGuard) -> None:
    # SELECT INTO creates a new table on T-SQL
    sql = "SELECT id, name INTO users_backup FROM users"
    with pytest.raises(ASTSecurityViolation):
        guard.validate(sql, dialect="tsql")


def test_rejects_unconstrained_cartesian_join(guard: ASTGuard) -> None:
    # unconstrained cross joins can generate millions of rows and lock memory
    bad_queries = [
        "SELECT * FROM orders CROSS JOIN customers",
        "SELECT * FROM orders, customers",
    ]
    for sql in bad_queries:
        with pytest.raises(ASTSecurityViolation):
            guard.validate(sql)


def test_allows_constrained_joins(guard: ASTGuard) -> None:
    valid_queries = [
        "SELECT * FROM orders JOIN customers ON orders.cust_id = customers.id",
        "SELECT * FROM orders, customers WHERE orders.cust_id = customers.id",
    ]
    for sql in valid_queries:
        guard.validate(sql)


def test_rewrites_postgres_limit(guard: ASTGuard) -> None:
    # missing limit should get default limit
    res1 = guard.rewrite("SELECT id FROM users", dialect="postgres", max_rows=100)
    assert "LIMIT 100" in res1

    # smaller limit should be preserved
    res2 = guard.rewrite("SELECT id FROM users LIMIT 10", dialect="postgres", max_rows=100)
    assert "LIMIT 10" in res2

    # larger limit clamped down to max_rows
    res3 = guard.rewrite("SELECT id FROM users LIMIT 500", dialect="postgres", max_rows=100)
    assert "LIMIT 100" in res3


def test_rewrites_tsql_top_and_nolock(guard: ASTGuard) -> None:
    # tsql gets TOP 100 and WITH (NOLOCK) on tables
    res = guard.rewrite("SELECT id FROM users", dialect="tsql", max_rows=100)
    assert "TOP 100" in res
    assert "WITH (NOLOCK)" in res


def test_rewrites_tsql_clamps_existing_top(guard: ASTGuard) -> None:
    res_large = guard.rewrite("SELECT TOP 500 id FROM users", dialect="tsql", max_rows=100)
    assert "TOP 100" in res_large

    res_small = guard.rewrite("SELECT TOP 5 id FROM users", dialect="tsql", max_rows=100)
    assert "TOP 5" in res_small


def test_rewrites_tsql_skips_nolock_on_ctes(guard: ASTGuard) -> None:
    # CTE references should not have WITH (NOLOCK)
    sql = "WITH my_cte AS (SELECT id FROM users) SELECT * FROM my_cte"
    res = guard.rewrite(sql, dialect="tsql", max_rows=100)
    assert "users WITH (NOLOCK)" in res
    assert "my_cte WITH (NOLOCK)" not in res


def test_rewrite_rejects_security_violations(guard: ASTGuard) -> None:
    with pytest.raises(ASTSecurityViolation):
        guard.rewrite("DROP TABLE users", dialect="tsql")


def test_rejects_dangerous_functions_and_procedures(guard: ASTGuard) -> None:
    dangerous = [
        ("SELECT xp_cmdshell('dir')", "tsql"),
        ("SELECT sp_OACreate('WScript.Shell', 1)", "tsql"),
        ("SELECT xp_dirtree('C:\\\\', 1, 1)", "tsql"),
        ("SELECT * FROM OPENROWSET('SQLNCLI', 'Server=x', 'SELECT 1')", "tsql"),
        ("SELECT * FROM OPENDATASOURCE('SQLNCLI', 'Data Source=x').db.dbo.users", "tsql"),
        ("SELECT * FROM OPENQUERY(linked_server, 'SELECT 1')", "tsql"),
        ("SELECT load_extension('/tmp/evil.so')", "sqlite"),
        ("SELECT pg_read_file('/etc/passwd')", "postgres"),
    ]
    for sql, dialect in dangerous:
        with pytest.raises(ASTSecurityViolation):
            guard.validate(sql, dialect=dialect)


def test_rejects_explicit_cross_join_even_with_where(guard: ASTGuard) -> None:
    sql = "SELECT * FROM orders CROSS JOIN customers WHERE 1 = 1"
    with pytest.raises(ASTSecurityViolation):
        guard.validate(sql)


def test_subquery_constrained_join_allowed_without_outer_where(guard: ASTGuard) -> None:
    sql = "SELECT * FROM (SELECT * FROM a JOIN b ON a.id = b.id) AS sub"
    stmt = guard.validate(sql)
    assert stmt is not None


def test_clamped_row_limit_with_parentheses_top(guard: ASTGuard) -> None:
    # TOP (5) should not be overridden and expanded to 100
    res = guard.rewrite("SELECT TOP (5) id FROM users", dialect="tsql", max_rows=100)
    assert "TOP 5" in res or "TOP (5)" in res
    assert "TOP 100" not in res


def test_rewrites_negative_max_rows_clamped(guard: ASTGuard) -> None:
    res = guard.rewrite("SELECT id FROM users", dialect="postgres", max_rows=-1)
    assert "LIMIT 1" in res
    assert "LIMIT -1" not in res


def test_tsql_skips_nolock_on_table_valued_functions(guard: ASTGuard) -> None:
    sql = "SELECT value FROM STRING_SPLIT('a,b,c', ',')"
    res = guard.rewrite(sql, dialect="tsql", max_rows=100)
    assert "STRING_SPLIT" in res
    assert "WITH (NOLOCK)" not in res
