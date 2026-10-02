"""Steiner Minimal Join Tree solver for multi-table relational joins."""

import networkx as nx
from networkx.algorithms.approximation import steiner_tree

from schema_compass.graph.schema_graph import SchemaGraph
from schema_compass.models import DisconnectedGraphError, JoinStep, JoinTree


class SteinerJoinSolver:
    """Builds minimal-cost join trees across arbitrary tables."""

    def __init__(self, schema_graph: SchemaGraph) -> None:
        self.schema_graph = schema_graph

    def solve(self, terminals: list[str], root_table: str | None = None) -> JoinTree:
        if not terminals:
            raise ValueError("terminals list cannot be empty")

        unique_terminals = list(dict.fromkeys(terminals))

        for t in unique_terminals:
            if not self.schema_graph.graph.has_node(t):
                raise DisconnectedGraphError(f"table '{t}' not in schema graph")

        if len(unique_terminals) == 1:
            return JoinTree(
                root_table=unique_terminals[0],
                steps=[],
                tables_included=unique_terminals,
                total_weight=0.0,
            )

        # networkx steiner_tree throws KeyError on disjoint graphs
        # verify all terminals share a connected component first
        first = unique_terminals[0]
        connected_comp = nx.node_connected_component(self.schema_graph.graph, first)
        for t in unique_terminals[1:]:
            if t not in connected_comp:
                raise DisconnectedGraphError(f"table '{t}' has no relational path to '{first}'")

        try:
            # isolate subgraph; passing full G crashes if orphan tables exist
            subgraph = self.schema_graph.graph.subgraph(connected_comp)
            tree = steiner_tree(
                subgraph,
                terminal_nodes=unique_terminals,
                weight="weight",
            )
        except Exception as err:
            raise DisconnectedGraphError(f"failed to compute join tree: {err}") from err

        if not root_table or root_table not in tree:
            root_table = self._select_optimal_root(tree, unique_terminals)

        steps: list[JoinStep] = []
        total_weight = 0.0

        for u, v in nx.bfs_edges(tree, root_table):
            edge_meta = self.schema_graph.get_edge_metadata(u, v)
            total_weight += edge_meta.get("weight", 1.0)

            rel_from = edge_meta.get("from_col")
            rel_to = edge_meta.get("to_col")

            contract_u = self.schema_graph.get_contract(u)
            u_is_source = False
            if contract_u:
                for rel in contract_u.relationships:
                    if rel.target_table == v:
                        u_is_source = True
                        rel_from = rel.source_column
                        rel_to = rel.target_column
                        break

            if not u_is_source:
                contract_v = self.schema_graph.get_contract(v)
                if contract_v:
                    for rel in contract_v.relationships:
                        if rel.target_table == u:
                            rel_from = rel.target_column
                            rel_to = rel.source_column
                            break

            steps.append(
                JoinStep(
                    from_table=u,
                    from_column=rel_from or "id",
                    to_table=v,
                    to_column=rel_to or "id",
                    join_type="JOIN",
                )
            )

        return JoinTree(
            root_table=root_table,
            steps=steps,
            tables_included=list(tree.nodes),
            total_weight=total_weight,
        )

    def _select_optimal_root(self, tree: nx.Graph, terminals: list[str]) -> str:
        # bias root toward fact tables so the SQL naturally starts FROM the fact
        candidate = terminals[0]
        max_rows = -1

        for t in terminals:
            contract = self.schema_graph.get_contract(t)
            row_count = contract.row_count if contract else 0
            if contract and contract.role == "fact":
                row_count *= 10

            if row_count > max_rows:
                max_rows = row_count
                candidate = t

        return candidate
