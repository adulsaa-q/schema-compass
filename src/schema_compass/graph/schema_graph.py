"""Schema topology graph builder using NetworkX."""

from typing import Any

import networkx as nx

from schema_compass.models import DisconnectedGraphError, Relationship, TableContract


class SchemaGraph:
    """Represents relational database tables and foreign keys as a weighted graph."""

    def __init__(self) -> None:
        self.graph = nx.Graph()
        self._table_contracts: dict[str, TableContract] = {}

    @property
    def tables(self) -> list[str]:
        """Return list of all registered table names."""
        return list(self.graph.nodes)

    def add_table(self, contract: TableContract) -> None:
        """Register a table and its relationships in the topology graph."""
        self._table_contracts[contract.name] = contract
        self.graph.add_node(contract.name, contract=contract)

        for rel in contract.relationships:
            self.add_relationship(rel)

    def load_tables(self, contracts: list[TableContract]) -> None:
        """Bulk load a list of table contracts."""
        for c in contracts:
            self.add_table(c)

    def add_relationship(self, rel: Relationship) -> None:
        """Add a weighted relationship edge between two tables."""
        # Ensure both endpoints exist in graph
        if not self.graph.has_node(rel.source_table):
            self.graph.add_node(rel.source_table)
        if not self.graph.has_node(rel.target_table):
            self.graph.add_node(rel.target_table)

        self.graph.add_edge(
            rel.source_table,
            rel.target_table,
            weight=rel.weight,
            from_col=rel.source_column,
            to_col=rel.target_column,
            rel_type=rel.relationship_type,
        )

    def has_edge(self, u: str, v: str) -> bool:
        """Check if an edge exists between two tables."""
        return self.graph.has_edge(u, v)

    def get_edge_metadata(self, u: str, v: str) -> dict[str, Any]:
        """Return relationship edge metadata between u and v."""
        if not self.graph.has_edge(u, v):
            raise KeyError(f"No edge between {u} and {v}")
        return self.graph[u][v]

    def get_contract(self, table_name: str) -> TableContract | None:
        """Return the TableContract for a given table name."""
        return self._table_contracts.get(table_name)

    def get_shortest_path(self, source: str, target: str) -> list[str]:
        """
        Calculate the lowest-weight path between two tables using Dijkstra.
        Raises DisconnectedGraphError if unreachable.
        """
        if not self.graph.has_node(source):
            raise DisconnectedGraphError(f"Table '{source}' not found in schema graph.")
        if not self.graph.has_node(target):
            raise DisconnectedGraphError(f"Table '{target}' not found in schema graph.")

        try:
            return nx.shortest_path(self.graph, source=source, target=target, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound) as err:
            raise DisconnectedGraphError(
                f"No join path exists between '{source}' and '{target}'."
            ) from err
