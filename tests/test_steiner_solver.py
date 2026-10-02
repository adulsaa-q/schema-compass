"""Tests for Steiner Minimal Join Tree solver."""

import pytest

from schema_compass.graph.schema_graph import SchemaGraph
from schema_compass.graph.steiner_solver import SteinerJoinSolver
from schema_compass.models import DisconnectedGraphError
from tests.fixtures.sample_schema import SAMPLE_TABLES


@pytest.fixture
def solver() -> SteinerJoinSolver:
    """Instantiate SteinerJoinSolver with the sample enterprise schema graph."""
    sg = SchemaGraph()
    sg.load_tables(list(SAMPLE_TABLES.values()))
    return SteinerJoinSolver(sg)


def test_single_table_join_tree(solver: SteinerJoinSolver):
    tree = solver.solve(["orders"])
    assert tree.root_table == "orders"
    assert len(tree.steps) == 0
    assert tree.to_sql_from_clause() == "FROM orders"


def test_two_table_join_tree(solver: SteinerJoinSolver):
    tree = solver.solve(["orders", "customers"])
    assert len(tree.steps) == 1
    assert tree.steps[0].to_table in ("orders", "customers")
    sql = tree.to_sql_from_clause()
    assert "JOIN" in sql
    assert "customer_id" in sql


def test_three_table_multi_hop_steiner_tree(solver: SteinerJoinSolver):
    # order_items, customers, categories require bridging through orders and products
    terminals = ["order_items", "customers", "categories"]
    tree = solver.solve(terminals)

    for t in terminals:
        assert t in tree.tables_included

    assert "orders" in tree.tables_included
    assert "products" in tree.tables_included
    assert len(tree.steps) == 4

    sql = tree.to_sql_from_clause()
    assert "order_items" in sql
    assert "orders" in sql
    assert "customers" in sql
    assert "products" in sql
    assert "categories" in sql


def test_disconnected_terminal_raises_error(solver: SteinerJoinSolver):
    with pytest.raises(DisconnectedGraphError):
        solver.solve(["orders", "audit_logs"])
