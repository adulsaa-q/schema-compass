"""Deep Adversarial Matrix and Edge-Case Stress Testing.

Covers:
1. Wildcard (SELECT *) DLP evasion on sensitive entities.
2. Side-channel time-delay and DoS functions (pg_sleep, sleep, benchmark, randomblob).
3. Tautological and unlinked comma joins (WHERE customers.id = customers.id).
4. Case-insensitive table resolution in schema topology.
"""

import pytest

from schema_compass.graph.schema_graph import SchemaGraph
from schema_compass.graph.steiner_solver import SteinerJoinSolver
from schema_compass.models import ColumnInfo, Relationship, TableContract
from schema_compass.safety.ast_guard import ASTGuard, ASTSecurityViolation


@pytest.fixture
def guard() -> ASTGuard:
    return ASTGuard()


def test_dlp_blocks_wildcard_star_on_sensitive_tables(guard: ASTGuard) -> None:
    # Wildcard queries on sensitive tables must be blocked to prevent bulk PII dumping
    evasion_queries = [
        "SELECT * FROM employees",
        "SELECT * FROM users",
        "SELECT e.* FROM employee e",
        "SELECT * FROM payroll_records",
        "SELECT * FROM customer_accounts",
    ]
    blocked = {"employees", "users", "employee", "payroll_records", "customer_accounts"}
    for sql in evasion_queries:
        with pytest.raises(ASTSecurityViolation, match="Wildcard SELECT"):
            guard.validate(sql, blocked_tables=blocked)

    # Safe non-sensitive tables should remain unblocked
    safe_queries = [
        "SELECT * FROM dim_date",
        "SELECT * FROM categories",
        "SELECT p.* FROM products p",
    ]
    for sql in safe_queries:
        stmt = guard.validate(sql, block_unaggregated_pii=True)
        assert stmt is not None


def test_prohibited_dos_and_side_channel_functions(guard: ASTGuard) -> None:
    # Time-delay blind injection, DoS, and session alteration functions must be blocked
    malicious_queries = [
        "SELECT pg_sleep(10)",
        "SELECT sleep(5) FROM products",
        "SELECT benchmark(10000000, 'test')",
        "SELECT randomblob(1000000000)",
        "SELECT pg_terminate_backend(1234)",
        "SELECT set_config('work_mem', '1GB', false)",
    ]
    for sql in malicious_queries:
        with pytest.raises(ASTSecurityViolation, match="Prohibited function"):
            guard.validate(sql)


def test_cartesian_join_blocks_tautological_and_unlinked_predicates(guard: ASTGuard) -> None:
    # Comma joins where predicate is tautological or single-table only are still Cartesian products
    bad_comma_joins = [
        "SELECT * FROM orders, customers WHERE customers.id = customers.id",
        "SELECT * FROM orders, customers WHERE customers.status = 'ACTIVE'",
    ]
    for sql in bad_comma_joins:
        with pytest.raises(ASTSecurityViolation, match="Cartesian"):
            guard.validate(sql)

    # Legitimate equijoin across different tables in WHERE is permitted
    valid_comma_join = "SELECT * FROM orders, customers WHERE orders.customer_id = customers.id"
    stmt = guard.validate(valid_comma_join)
    assert stmt is not None


def test_schema_graph_case_insensitive_table_resolution() -> None:
    # Enterprise schemas frequently mix casing across database systems
    graph = SchemaGraph()
    contract_cust = TableContract(
        name="Customers",
        columns=[ColumnInfo(name="CustomerID", data_type="int", is_pk=True)],
        relationships=[
            Relationship(
                source_table="Orders",
                source_column="CustomerID",
                target_table="Customers",
                target_column="CustomerID",
                weight=1.0,
            )
        ],
    )
    contract_ord = TableContract(
        name="Orders",
        columns=[
            ColumnInfo(name="OrderID", data_type="int", is_pk=True),
            ColumnInfo(name="CustomerID", data_type="int"),
        ],
        relationships=[],
    )
    graph.load_tables([contract_cust, contract_ord])

    # Case-insensitive contract retrieval
    assert graph.get_contract("customers") is not None
    assert graph.get_contract("CUSTOMERS") is not None
    assert graph.get_contract("Customers") is not None

    # Steiner solver with mixed case terminals
    solver = SteinerJoinSolver(graph)
    tree = solver.solve(["customers", "ORDERS"])
    assert len(tree.steps) == 1
    assert tree.total_weight == 1.0
