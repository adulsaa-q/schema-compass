import pytest

from schema_compass.server import create_server
from tests.fixtures.sample_schema import SAMPLE_CONTRACTS


@pytest.fixture
def server():
    return create_server(contracts=SAMPLE_CONTRACTS)


@pytest.mark.anyio
async def test_server_lists_all_tools(server) -> None:
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}
    expected = {
        "search_catalog",
        "get_join_tree",
        "get_table_contract",
        "explain_metric",
        "execute_safe_query",
    }
    assert expected.issubset(tool_names)


@pytest.mark.anyio
async def test_search_catalog_tool(server) -> None:
    res = await server.call_tool("search_catalog", {"query": "customer"})
    text = res.content[0].text
    assert "customers" in text.lower()


@pytest.mark.anyio
async def test_get_join_tree_tool(server) -> None:
    res = await server.call_tool("get_join_tree", {"tables": ["orders", "products"]})
    text = res.content[0].text
    assert "FROM order_items" in text
    assert "orders" in text
    assert "products" in text


@pytest.mark.anyio
async def test_get_table_contract_tool(server) -> None:
    res = await server.call_tool("get_table_contract", {"table_name": "orders"})
    text = res.content[0].text
    assert "dbo.orders" in text
    assert "order_id" in text


@pytest.mark.anyio
async def test_explain_metric_tool(server) -> None:
    res = await server.call_tool("explain_metric", {"metric_name": "total_amount"})
    text = res.content[0].text
    assert "orders" in text.lower()
    assert "total_amount" in text


@pytest.mark.anyio
async def test_execute_safe_query_tool_valid(server) -> None:
    res = await server.call_tool(
        "execute_safe_query",
        {"sql": "SELECT order_id FROM orders", "dialect": "tsql", "max_rows": 50},
    )
    text = res.content[0].text
    assert "TOP 50" in text
    assert "WITH (NOLOCK)" in text


@pytest.mark.anyio
async def test_execute_safe_query_tool_rejects_dangerous(server) -> None:
    res = await server.call_tool(
        "execute_safe_query",
        {"sql": "DROP TABLE orders", "dialect": "tsql"},
    )
    text = res.content[0].text
    assert "Security violation" in text or "error" in text.lower()


@pytest.mark.anyio
async def test_get_schema_diagram_tool(server) -> None:
    res = await server.call_tool("get_schema_diagram", {"tables": ["orders", "customers"]})
    text = res.content[0].text
    assert "erDiagram" in text
    assert "orders" in text
    assert "customers" in text


def test_load_contracts_from_json(tmp_path) -> None:
    import json

    from schema_compass.server import load_contracts_from_source

    test_contracts_data = [
        {
            "name": "dim_store",
            "schema_name": "dbo",
            "row_count": 100,
            "role": "dimension",
            "columns": [{"name": "store_id", "data_type": "INT", "is_pk": True}],
            "relationships": [],
        }
    ]
    json_file = tmp_path / "schema.json"
    json_file.write_text(json.dumps(test_contracts_data), encoding="utf-8")

    contracts = load_contracts_from_source("json", str(json_file))
    assert len(contracts) == 1
    assert contracts[0].name == "dim_store"


def test_load_contracts_from_sqlite(tmp_path) -> None:
    import sqlite3

    from schema_compass.server import load_contracts_from_source

    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE products (product_id INT PRIMARY KEY, name TEXT)")
    conn.close()

    contracts = load_contracts_from_source("sqlite", str(db_path))
    assert len(contracts) == 1
    assert contracts[0].name == "products"


@pytest.mark.anyio
async def test_server_uses_the_guard_it_is_given() -> None:
    from schema_compass.safety.ast_guard import ASTGuard

    strict = create_server(contracts=SAMPLE_CONTRACTS)
    open_ = create_server(
        contracts=SAMPLE_CONTRACTS, guard=ASTGuard(extra_allowed_functions={"my_udf"})
    )
    sql = {"sql": "SELECT my_udf(order_id) FROM orders", "dialect": "postgres"}
    assert (
        "not on the allowlist"
        in (await strict.call_tool("execute_safe_query", sql)).content[0].text
    )
    assert (
        (await open_.call_tool("execute_safe_query", sql)).content[0].text.startswith("Validated")
    )


def test_cli_flags_build_the_guard() -> None:
    from schema_compass.server import build_guard

    guard = build_guard(
        allow_functions=["MY_UDF", "other"], allow_recursive_cte=True, allow_system_catalogs=True
    )
    assert guard.extra_allowed_functions == {"my_udf", "other"}
    assert guard.allow_recursive_cte and guard.allow_system_catalogs
