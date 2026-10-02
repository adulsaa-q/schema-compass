"""Schema topology graph builder using NetworkX."""

from typing import Any

import networkx as nx

from schema_compass.models import DisconnectedGraphError, Relationship, TableContract


class SchemaGraph:
    """Relational schema topology represented as an edge-weighted graph."""

    def __init__(self) -> None:
        self.graph = nx.Graph()
        self._table_contracts: dict[str, TableContract] = {}

    @property
    def tables(self) -> list[str]:
        return list(self.graph.nodes)

    def add_table(self, contract: TableContract) -> None:
        self._table_contracts[contract.name] = contract
        self.graph.add_node(contract.name, contract=contract)

        for rel in contract.relationships:
            self.add_relationship(rel)

    def load_tables(self, contracts: list[TableContract]) -> None:
        for c in contracts:
            self.add_table(c)

    load_contracts = load_tables

    def add_relationship(self, rel: Relationship) -> None:
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
        return self.graph.has_edge(u, v)

    def get_edge_metadata(self, u: str, v: str) -> dict[str, Any]:
        if not self.graph.has_edge(u, v):
            raise KeyError(f"no edge between {u} and {v}")
        return self.graph[u][v]

    def get_contract(self, table_name: str) -> TableContract | None:
        return self._table_contracts.get(table_name)

    def get_shortest_path(self, source: str, target: str) -> list[str]:
        if not self.graph.has_node(source):
            raise DisconnectedGraphError(f"table '{source}' not in schema graph")
        if not self.graph.has_node(target):
            raise DisconnectedGraphError(f"table '{target}' not in schema graph")

        try:
            return nx.shortest_path(self.graph, source=source, target=target, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound) as err:
            raise DisconnectedGraphError(f"no join path between '{source}' and '{target}'") from err
