"""A join that walks from the "one" side to the "many" side repeats rows and inflates SUM/COUNT."""

import sqlite3

import pytest

from schema_compass.dialects.sqlite import SQLiteAdapter
from schema_compass.graph.schema_graph import SchemaGraph
from schema_compass.graph.steiner_solver import SteinerJoinSolver
from schema_compass.models import ColumnInfo, JoinTree, Relationship, TableContract
from schema_compass.sample_schema import SAMPLE_CONTRACTS
from schema_compass.server import create_server


def contracts_from_chinook() -> list[TableContract]:
    from evals.eval_chinook_showcase import CHINOOK_DDL

    conn = sqlite3.connect(":memory:")
    conn.executescript(CHINOOK_DDL)
    sizes = {"tracks": 3503, "invoice_items": 2240, "playlist_track": 8715}
    return [
        c.model_copy(update={"row_count": sizes.get(c.name, 50)})
        for c in SQLiteAdapter(conn).extract_contracts()
    ]


def solve(contracts: list[TableContract], tables: list[str]) -> JoinTree:
    graph = SchemaGraph()
    graph.load_contracts(contracts)
    return SteinerJoinSolver(graph).solve(tables)


def test_steps_toward_the_one_side_are_many_to_one() -> None:
    tree = solve(contracts_from_chinook(), ["customers", "genres"])
    assert {s.cardinality for s in tree.steps} == {"many_to_one"}
    assert tree.fan_out_warnings() == []


def test_a_step_toward_the_many_side_is_flagged() -> None:
    tree = solve(contracts_from_chinook(), ["playlists", "customers"])
    flagged = [s for s in tree.steps if s.cardinality == "one_to_many"]
    assert [s.to_table for s in flagged] == ["playlist_track"]
    warnings = tree.fan_out_warnings()
    assert len(warnings) == 1
    assert "playlist_track" in warnings[0] and "tracks" in warnings[0]


def test_warning_names_the_tables_whose_values_repeat() -> None:
    tree = solve(contracts_from_chinook(), ["playlists", "customers"])
    text = tree.fan_out_warnings()[0]
    for repeated in ("invoice_items", "invoices", "customers", "tracks"):
        assert repeated in text


def test_sample_schema_star_joins_have_no_warning() -> None:
    for tables in (["orders", "products"], ["customers", "products"], ["orders", "countries"]):
        assert solve(SAMPLE_CONTRACTS, tables).fan_out_warnings() == []


def _table(name: str, rows: int, *refs: str) -> TableContract:
    cols = [ColumnInfo(name=f"{name}_id", data_type="INT", is_pk=True)]
    rels = []
    for ref in refs:
        cols.append(ColumnInfo(name=f"{ref}_id", data_type="INT", is_fk=True))
        rels.append(
            Relationship(
                source_table=name,
                source_column=f"{ref}_id",
                target_table=ref,
                target_column=f"{ref}_id",
            )
        )
    return TableContract(name=name, columns=cols, relationships=rels, row_count=rows)


def test_two_one_to_many_branches_are_called_out_together() -> None:
    contracts = [
        _table("customer", 100),
        _table("ticket", 500, "customer"),
        _table("invoice", 400, "customer"),
        _table("note", 900, "customer"),
    ]
    tree = solve(contracts, ["ticket", "invoice", "note"])
    warnings = tree.fan_out_warnings()
    assert any("multiply each other" in w for w in warnings)


def test_a_chain_of_many_to_one_steps_has_no_warning() -> None:
    contracts = [
        _table("country", 10),
        _table("region", 50, "country"),
        _table("store", 200, "region"),
        _table("sale", 5000, "store"),
    ]
    assert solve(contracts, ["sale", "country"]).fan_out_warnings() == []


@pytest.mark.anyio
async def test_server_appends_the_warning_after_the_sql() -> None:
    server = create_server(contracts=contracts_from_chinook())
    risky = (
        (await server.call_tool("get_join_tree", {"tables": ["playlists", "customers"]}))
        .content[0]
        .text
    )
    safe = (
        (await server.call_tool("get_join_tree", {"tables": ["customers", "genres"]}))
        .content[0]
        .text
    )
    assert "FROM invoice_items" in risky
    assert "Warning" in risky and "playlist_track" in risky.split("Warning", 1)[1]
    assert "Warning" not in safe
