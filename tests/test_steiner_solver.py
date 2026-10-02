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


def test_intermediate_fact_table_selected_as_root():
    from schema_compass.models import Relationship, TableContract

    sg = SchemaGraph()
    # Star schema: dim_customer <- fact_sales -> dim_store
    dim_cust = TableContract(name="dim_customer", role="dimension", row_count=500)
    dim_store = TableContract(name="dim_store", role="dimension", row_count=50)
    fact_sales = TableContract(
        name="fact_sales",
        role="fact",
        row_count=1_000_000,
        relationships=[
            Relationship(
                source_table="fact_sales",
                source_column="customer_id",
                target_table="dim_customer",
                target_column="customer_id",
                weight=1.0,
            ),
            Relationship(
                source_table="fact_sales",
                source_column="store_id",
                target_table="dim_store",
                target_column="store_id",
                weight=1.0,
            ),
        ],
    )
    sg.load_tables([dim_cust, dim_store, fact_sales])
    solver = SteinerJoinSolver(sg)

    # Terminals are dimensions only; fact_sales is an intermediate Steiner bridge
    tree = solver.solve(["dim_customer", "dim_store"])
    assert tree.root_table == "fact_sales"
    assert "fact_sales" in tree.tables_included
    assert len(tree.steps) == 2


def test_multigraph_retains_lowest_weight_edge():
    from schema_compass.models import Relationship, TableContract

    sg = SchemaGraph()
    t1 = TableContract(
        name="orders",
        relationships=[
            Relationship(
                source_table="orders",
                source_column="ship_addr_id",
                target_table="addresses",
                target_column="id",
                weight=1.0,
            ),
            Relationship(
                source_table="orders",
                source_column="bill_addr_id",
                target_table="addresses",
                target_column="id",
                weight=3.5,
            ),
        ],
    )
    t2 = TableContract(name="addresses")
    sg.load_tables([t1, t2])

    meta = sg.get_edge_metadata("orders", "addresses")
    assert meta["weight"] == 1.0
    assert meta["from_col"] == "ship_addr_id"
