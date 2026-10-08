import pytest

from schema_compass.models import ColumnInfo, TableContract
from schema_compass.search import search_contracts, tokenize
from tests.fixtures.sample_schema import SAMPLE_CONTRACTS


def _table(name: str, *cols: str, description: str | None = None) -> TableContract:
    return TableContract(
        name=name,
        schema_name="main",
        row_count=10,
        description=description,
        columns=[ColumnInfo(name=c, data_type="TEXT") for c in cols],
    )


CHINOOK_LIKE = [
    _table("Invoice", "InvoiceId", "CustomerId", "Total", "BillingCity"),
    _table("InvoiceLine", "InvoiceLineId", "InvoiceId", "TrackId", "UnitPrice", "Quantity"),
    _table("Customer", "CustomerId", "FirstName", "LastName", "Email"),
    _table("Track", "TrackId", "Name", "GenreId", "UnitPrice"),
    _table("Genre", "GenreId", "Name"),
]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("InvoiceLine", ["invoice", "line"]),
        ("customer_name", ["customer", "name"]),
        ("Invoice.Total", ["invoice", "total"]),
        ("tracks by genre", ["tracks", "genre"]),
        ("  The  of  ", []),
        ("", []),
        ("HTTPServer2", ["http", "server", "2"]),
    ],
)
def test_tokenize(text: str, expected: list[str]) -> None:
    assert tokenize(text) == expected


def test_single_word_keeps_original_ranking() -> None:
    hits = search_contracts(CHINOOK_LIKE, "invoice", top_k=5)
    assert [h.contract.name for h in hits][:2] == ["Invoice", "InvoiceLine"]


def test_multi_word_query_finds_table_and_column() -> None:
    hits = search_contracts(CHINOOK_LIKE, "invoice total", top_k=5)
    assert hits, "multi-word query must not return nothing"
    assert hits[0].contract.name == "Invoice"
    assert "Total" in hits[0].matched_columns


def test_words_split_across_table_and_column() -> None:
    hits = search_contracts(CHINOOK_LIKE, "customer email", top_k=5)
    assert hits[0].contract.name == "Customer"
    assert "Email" in hits[0].matched_columns


def test_plural_and_stopwords_are_ignored() -> None:
    hits = search_contracts(CHINOOK_LIKE, "tracks by genre", top_k=5)
    names = [h.contract.name for h in hits]
    assert {"Track", "Genre"} <= set(names)
    assert names[0] in {"Track", "Genre"}


def test_table_matching_more_words_ranks_higher() -> None:
    hits = search_contracts(CHINOOK_LIKE, "unit price track", top_k=5)
    assert [h.contract.name for h in hits][:2] == ["Track", "InvoiceLine"]


def test_dotted_reference_matches() -> None:
    hits = search_contracts(CHINOOK_LIKE, "Invoice.Total", top_k=5)
    assert hits[0].contract.name == "Invoice"


def test_snake_case_columns_match_spaced_query() -> None:
    hits = search_contracts(SAMPLE_CONTRACTS, "customer name", top_k=3)
    assert hits[0].contract.name == "customers"
    assert "customer_name" in hits[0].matched_columns


def test_top_k_is_respected_and_unmatched_returns_empty() -> None:
    assert len(search_contracts(CHINOOK_LIKE, "id", top_k=2)) == 2
    assert search_contracts(CHINOOK_LIKE, "zzzz nothing", top_k=5) == []


def test_only_stopwords_returns_empty() -> None:
    assert search_contracts(CHINOOK_LIKE, "by the", top_k=5) == []
