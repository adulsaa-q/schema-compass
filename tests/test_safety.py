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
