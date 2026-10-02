"""Tests for Column DLP (Data Loss Prevention) and Query Complexity Guardrails."""

import pytest

from schema_compass.safety.ast_guard import ASTGuard, ASTSecurityViolation


@pytest.fixture
def guard() -> ASTGuard:
    return ASTGuard()


def test_dlp_blocks_direct_pii_selection(guard: ASTGuard) -> None:
    # Direct selection of sensitive PII columns must be blocked
    queries = [
        "SELECT id, salary FROM employees",
        "SELECT citizen_id FROM citizens",
        "SELECT national_id, full_name FROM customers",
        "SELECT password_hash FROM user_credentials",
        "SELECT credit_card_number FROM payments",
    ]
    for sql in queries:
        with pytest.raises(ASTSecurityViolation, match="DLP Policy Violation"):
            guard.validate(sql)


def test_dlp_allows_aggregated_pii_metrics(guard: ASTGuard) -> None:
    # Aggregated metrics (AVG, SUM, COUNT) on sensitive columns must be permitted for analytics
    valid_queries = [
        "SELECT department_id, AVG(salary) AS avg_sal FROM employees GROUP BY department_id",
        "SELECT COUNT(citizen_id) AS total_citizens FROM citizens",
        "SELECT MIN(salary), MAX(salary) FROM employees",
        "SELECT COUNT(DISTINCT national_id) FROM customers",
    ]
    for sql in valid_queries:
        stmt = guard.validate(sql)
        assert stmt is not None


def test_dlp_respects_custom_blocked_columns(guard: ASTGuard) -> None:
    sql = "SELECT id, custom_secret_field FROM config"
    with pytest.raises(ASTSecurityViolation, match="DLP Policy Violation"):
        guard.validate(sql, blocked_columns={"custom_secret_field"})


def test_complexity_blocks_excessive_joins(guard: ASTGuard) -> None:
    # Construct a query with 12 joins when limit is 10
    joins = " ".join([f"JOIN t{i} ON t0.id = t{i}.id" for i in range(1, 13)])
    sql = f"SELECT t0.id FROM t0 {joins}"
    with pytest.raises(ASTSecurityViolation, match="Query complexity exceeded.*joins"):
        guard.validate(sql, max_joins=10)


def test_complexity_blocks_deeply_nested_subqueries(guard: ASTGuard) -> None:
    # Deeply nested subquery exceeding max_subquery_depth (e.g. 6 levels deep when max is 4)
    sql = "SELECT * FROM (SELECT * FROM (SELECT * FROM (SELECT * FROM (SELECT * FROM (SELECT 1 AS x) AS s5) AS s4) AS s3) AS s2) AS s1"
    with pytest.raises(ASTSecurityViolation, match="Query complexity exceeded.*depth"):
        guard.validate(sql, max_subquery_depth=4)
