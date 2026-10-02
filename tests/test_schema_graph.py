"""Tests for SchemaGraph topology building and shortest path resolution."""

import pytest

from schema_compass.graph.schema_graph import SchemaGraph
from schema_compass.models import DisconnectedGraphError
from tests.fixtures.sample_schema import SAMPLE_TABLES


@pytest.fixture
def graph() -> SchemaGraph:
    """Instantiate SchemaGraph populated with the sample enterprise tables."""
    sg = SchemaGraph()
    sg.load_tables(list(SAMPLE_TABLES.values()))
    return sg


def test_schema_graph_node_count(graph: SchemaGraph):
    assert len(graph.tables) == len(SAMPLE_TABLES)
    assert "orders" in graph.tables
    assert "customers" in graph.tables
    assert "audit_logs" in graph.tables


def test_schema_graph_has_edges(graph: SchemaGraph):
    assert graph.has_edge("orders", "customers")
    assert graph.has_edge("order_items", "orders")
    assert graph.has_edge("customers", "regions")
    assert not graph.has_edge("orders", "audit_logs")


def test_direct_shortest_path(graph: SchemaGraph):
    path = graph.get_shortest_path("orders", "customers")
    assert path == ["orders", "customers"]


def test_multi_hop_shortest_path(graph: SchemaGraph):
    # order_items -> products -> suppliers -> countries has total cost 3.0 vs 4.0 through orders
    path = graph.get_shortest_path("order_items", "countries")
    assert path == ["order_items", "products", "suppliers", "countries"]
    assert len(path) == 4


def test_disconnected_table_raises_error(graph: SchemaGraph):
    with pytest.raises(DisconnectedGraphError):
        graph.get_shortest_path("orders", "audit_logs")
