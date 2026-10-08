"""Table roles depend on how a table sits in the foreign-key graph, not on its own columns alone."""

import sqlite3

import pytest

from schema_compass.dialects.sqlite import SQLiteAdapter
from schema_compass.models import ColumnInfo, Relationship, TableContract
from schema_compass.profiler.kimball import refine_roles
from schema_compass.sample_schema import SAMPLE_CONTRACTS


def col(name: str, data_type: str = "INTEGER", pk: bool = False, fk: bool = False) -> ColumnInfo:
    return ColumnInfo(name=name, data_type=data_type, is_pk=pk, is_fk=fk)


def table(name: str, columns: list[ColumnInfo], *refs: str) -> TableContract:
    """A table whose foreign keys are `column->target` strings."""
    rels = []
    for ref in refs:
        column, target = ref.split("->")
        rels.append(
            Relationship(
                source_table=name, source_column=column, target_table=target, target_column="id"
            )
        )
    return TableContract(name=name, columns=columns, relationships=rels, row_count=100)


def roles(contracts: list[TableContract]) -> dict[str, str]:
    return {c.name: c.role for c in refine_roles(contracts)}


def chinook() -> list[TableContract]:
    money = "NUMERIC(10,2)"
    return [
        table(
            "Album",
            [col("AlbumId", pk=True), col("Title", "NVARCHAR"), col("ArtistId", fk=True)],
            "ArtistId->Artist",
        ),
        table("Artist", [col("ArtistId", pk=True), col("Name", "NVARCHAR")]),
        table(
            "Customer",
            [col("CustomerId", pk=True), col("LastName", "NVARCHAR"), col("SupportRepId", fk=True)],
            "SupportRepId->Employee",
        ),
        table(
            "Employee",
            [
                col("EmployeeId", pk=True),
                col("LastName", "NVARCHAR"),
                col("ReportsTo", fk=True),
                col("BirthDate", "DATETIME"),
                col("HireDate", "DATETIME"),
            ],
            "ReportsTo->Employee",
        ),
        table("Genre", [col("GenreId", pk=True), col("Name", "NVARCHAR")]),
        table(
            "Invoice",
            [
                col("InvoiceId", pk=True),
                col("CustomerId", fk=True),
                col("InvoiceDate", "DATETIME"),
                col("BillingCity", "NVARCHAR"),
                col("Total", money),
            ],
            "CustomerId->Customer",
        ),
        table(
            "InvoiceLine",
            [
                col("InvoiceLineId", pk=True),
                col("InvoiceId", fk=True),
                col("TrackId", fk=True),
                col("UnitPrice", money),
                col("Quantity"),
            ],
            "InvoiceId->Invoice",
            "TrackId->Track",
        ),
        table("MediaType", [col("MediaTypeId", pk=True), col("Name", "NVARCHAR")]),
        table("Playlist", [col("PlaylistId", pk=True), col("Name", "NVARCHAR")]),
        table(
            "PlaylistTrack",
            [col("PlaylistId", pk=True, fk=True), col("TrackId", pk=True, fk=True)],
            "PlaylistId->Playlist",
            "TrackId->Track",
        ),
        table(
            "Track",
            [
                col("TrackId", pk=True),
                col("Name", "NVARCHAR"),
                col("AlbumId", fk=True),
                col("MediaTypeId", fk=True),
                col("GenreId", fk=True),
                col("Milliseconds"),
                col("UnitPrice", money),
            ],
            "AlbumId->Album",
            "MediaTypeId->MediaType",
            "GenreId->Genre",
        ),
    ]


def test_chinook_roles() -> None:
    assert roles(chinook()) == {
        "Album": "dimension",
        "Artist": "dimension",
        "Customer": "dimension",
        "Employee": "dimension",
        "Genre": "dimension",
        "Invoice": "fact",
        "InvoiceLine": "fact",
        "MediaType": "dimension",
        "Playlist": "dimension",
        "PlaylistTrack": "bridge",
        "Track": "dimension",
    }


def test_a_product_with_a_price_is_not_a_fact_just_because_it_has_foreign_keys() -> None:
    result = roles(
        [
            table("category", [col("category_id", pk=True), col("label", "TEXT")]),
            table("brand", [col("brand_id", pk=True), col("label", "TEXT")]),
            table(
                "product",
                [
                    col("product_id", pk=True),
                    col("category_id", fk=True),
                    col("brand_id", fk=True),
                    col("list_price", "DECIMAL(10,2)"),
                    col("created_at", "TIMESTAMP"),
                ],
                "category_id->category",
                "brand_id->brand",
            ),
            table("store", [col("store_id", pk=True), col("city", "TEXT")]),
            table(
                "sale_line",
                [
                    col("sale_line_id", pk=True),
                    col("product_id", fk=True),
                    col("store_id", fk=True),
                    col("quantity"),
                    col("line_amount", "DECIMAL(12,2)"),
                ],
                "product_id->product",
                "store_id->store",
            ),
        ]
    )
    assert result["product"] == "dimension"
    assert result["sale_line"] == "fact"


def test_a_dated_header_with_an_additive_total_is_a_fact() -> None:
    result = roles(
        [
            table("shop", [col("shop_id", pk=True), col("city", "TEXT")]),
            table(
                "sale_header",
                [
                    col("sale_id", pk=True),
                    col("shop_id", fk=True),
                    col("sale_date", "DATE"),
                    col("total_amount", "DECIMAL(12,2)"),
                ],
                "shop_id->shop",
            ),
            table(
                "sale_detail",
                [
                    col("detail_id", pk=True),
                    col("sale_id", fk=True),
                    col("item_id", fk=True),
                    col("qty"),
                ],
                "sale_id->sale_header",
                "item_id->item",
            ),
            table("item", [col("item_id", pk=True), col("label", "TEXT")]),
        ]
    )
    assert result["sale_header"] == "fact"
    assert result["sale_detail"] == "fact"
    assert result["shop"] == "dimension"
    assert result["item"] == "dimension"


def test_a_table_nothing_references_with_no_measures_stays_a_dimension() -> None:
    assert roles([table("settings", [col("key", "TEXT"), col("value", "TEXT")])]) == {
        "settings": "dimension"
    }


def test_explicit_prefixes_win_over_structure() -> None:
    result = roles(
        [
            table("dim_a", [col("a_id", pk=True)]),
            table("dim_b", [col("b_id", pk=True)]),
            table(
                "dim_odd",
                [
                    col("id", pk=True),
                    col("a_id", fk=True),
                    col("b_id", fk=True),
                    col("amount", "DECIMAL"),
                ],
                "a_id->dim_a",
                "b_id->dim_b",
            ),
            table("fact_tiny", [col("x", "TEXT")]),
        ]
    )
    assert result["dim_odd"] == "dimension"
    assert result["fact_tiny"] == "fact"


def test_singular_and_plural_canonical_names_agree() -> None:
    for name in ("invoice", "invoices"):
        assert roles([table(name, [col("id", pk=True)])])[name] == "fact"
    for name in ("customer", "customers"):
        assert roles([table(name, [col("id", pk=True)])])[name] == "dimension"


def test_self_reference_does_not_make_a_table_referenced() -> None:
    result = roles(
        [
            table("store", [col("store_id", pk=True)]),
            table("region", [col("region_id", pk=True)]),
            table(
                "txn",
                [
                    col("txn_id", pk=True),
                    col("parent_txn_id", fk=True),
                    col("store_id", fk=True),
                    col("region_id", fk=True),
                    col("amount", "DECIMAL(12,2)"),
                ],
                "parent_txn_id->txn",
                "store_id->store",
                "region_id->region",
            ),
        ]
    )
    assert result["txn"] == "fact"


def test_refine_does_not_mutate_its_input() -> None:
    original = chinook()
    before = {c.name: c.role for c in original}
    refine_roles(original)
    assert {c.name: c.role for c in original} == before


def test_builtin_sample_schema_keeps_the_roles_that_follow_from_its_structure() -> None:
    result = roles(SAMPLE_CONTRACTS)
    assert result["orders"] == "fact"
    assert result["order_items"] == "fact"
    for name in ("customers", "products", "regions", "countries"):
        assert result[name] == "dimension"


def _chinook_from_sqlite(row_counts: dict[str, int] | None = None) -> list[TableContract]:
    from evals.eval_chinook_showcase import CHINOOK_DDL

    conn = sqlite3.connect(":memory:")
    conn.executescript(CHINOOK_DDL)
    contracts = SQLiteAdapter(conn).extract_contracts()
    if row_counts:
        contracts = [
            c.model_copy(update={"row_count": row_counts.get(c.name, 50)}) for c in contracts
        ]
    return contracts


def test_sqlite_adapter_applies_the_refinement() -> None:
    by_name = {c.name: c.role for c in _chinook_from_sqlite()}
    assert by_name["tracks"] == "dimension"
    assert by_name["invoice_items"] == "fact"
    assert by_name["invoices"] == "fact"
    assert by_name["playlist_track"] == "bridge"
    assert by_name["employees"] == "dimension"


@pytest.mark.anyio
async def test_join_tree_starts_from_the_line_level_fact() -> None:
    from schema_compass.server import create_server

    # the biggest dimension (tracks) is larger than the line-level fact, which used to win the root
    server = create_server(contracts=_chinook_from_sqlite({"tracks": 3503, "invoice_items": 2240}))
    reply = await server.call_tool("get_join_tree", {"tables": ["customers", "genres"]})
    assert "FROM invoice_items" in reply.content[0].text
