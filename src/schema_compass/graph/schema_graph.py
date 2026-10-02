"""Schema topology graph builder using NetworkX."""

from typing import Any

import networkx as nx

from schema_compass.models import DisconnectedGraphError, Relationship, TableContract


class SchemaGraph:
    """Relational schema topology represented as an edge-weighted graph."""

    def __init__(self) -> None:
        self.graph = nx.Graph()
        self._table_contracts: dict[str, TableContract] = {}
        self._ci_map: dict[str, str] = {}

    @property
    def tables(self) -> list[str]:
        return list(self.graph.nodes)

    def resolve_table_name(self, name: str) -> str:
        """Resolve a table name case-insensitively to its canonical graph node name."""
        if self.graph.has_node(name):
            return name
        return self._ci_map.get(name.lower(), name)

    def has_node(self, table_name: str) -> bool:
        canonical = self.resolve_table_name(table_name)
        return self.graph.has_node(canonical)

    def add_table(self, contract: TableContract) -> None:
        self._table_contracts[contract.name] = contract
        self._ci_map[contract.name.lower()] = contract.name
        self.graph.add_node(contract.name, contract=contract)

        for rel in contract.relationships:
            self.add_relationship(rel)

    def load_tables(self, contracts: list[TableContract]) -> None:
        for c in contracts:
            self.add_table(c)

    load_contracts = load_tables

    def add_relationship(self, rel: Relationship) -> None:
        src = self.resolve_table_name(rel.source_table)
        tgt = self.resolve_table_name(rel.target_table)
        if not self.graph.has_node(src):
            self.graph.add_node(src)
        if not self.graph.has_node(tgt):
            self.graph.add_node(tgt)

        # Retain minimal-weight relationship if edge already exists
        if self.graph.has_edge(src, tgt):
            existing_weight = self.graph[src][tgt].get("weight", float("inf"))
            if rel.weight >= existing_weight:
                return

        self.graph.add_edge(
            src,
            tgt,
            weight=rel.weight,
            source_table=src,
            target_table=tgt,
            source_col=rel.source_column,
            target_col=rel.target_column,
            from_col=rel.source_column,
            to_col=rel.target_column,
            rel_type=rel.relationship_type,
        )

    def has_edge(self, u: str, v: str) -> bool:
        u_canon = self.resolve_table_name(u)
        v_canon = self.resolve_table_name(v)
        return self.graph.has_edge(u_canon, v_canon)

    def get_edge_metadata(self, u: str, v: str) -> dict[str, Any]:
        u_canon = self.resolve_table_name(u)
        v_canon = self.resolve_table_name(v)
        if not self.graph.has_edge(u_canon, v_canon):
            raise KeyError(f"no edge between {u} and {v}")
        return self.graph[u_canon][v_canon]

    def get_contract(self, table_name: str) -> TableContract | None:
        canonical = self.resolve_table_name(table_name)
        return self._table_contracts.get(canonical)

    def get_shortest_path(self, source: str, target: str) -> list[str]:
        src_canon = self.resolve_table_name(source)
        tgt_canon = self.resolve_table_name(target)
        if not self.graph.has_node(src_canon):
            raise DisconnectedGraphError(f"table '{source}' not in schema graph")
        if not self.graph.has_node(tgt_canon):
            raise DisconnectedGraphError(f"table '{target}' not in schema graph")

        try:
            return nx.shortest_path(self.graph, source=src_canon, target=tgt_canon, weight="weight")
        except (nx.NetworkXNoPath, nx.NodeNotFound) as err:
            raise DisconnectedGraphError(f"no join path between '{source}' and '{target}'") from err
