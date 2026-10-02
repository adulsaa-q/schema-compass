import sqlite3

import pytest

from schema_compass.dialects.sqlite import SQLiteAdapter
from schema_compass.graph.schema_graph import SchemaGraph
from schema_compass.graph.steiner_solver import SteinerJoinSolver


@pytest.fixture
def sqlite_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    # create sample relational schema in sqlite
    cursor.executescript(
        """
        CREATE TABLE customers (
            customer_id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT
        );

        CREATE TABLE orders (
            order_id INTEGER PRIMARY KEY,
            customer_id INTEGER NOT NULL,
            order_date TEXT NOT NULL,
            total_amount REAL,
            FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
        );

        CREATE TABLE order_items (
            item_id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders (order_id)
        );
        """
    )
    # insert dummy data to verify row counting and sample extraction
    cursor.execute("INSERT INTO customers VALUES (1, 'Alice', 'alice@example.com')")
    cursor.execute("INSERT INTO orders VALUES (101, 1, '2026-10-01', 99.50)")
    cursor.execute("INSERT INTO order_items VALUES (1001, 101, 'Widget A', 2)")
    conn.commit()

    yield conn
    conn.close()


def test_sqlite_adapter_extracts_contracts(sqlite_conn: sqlite3.Connection) -> None:
    adapter = SQLiteAdapter(sqlite_conn)
    contracts = adapter.extract_contracts()

    # should extract 3 tables
    table_names = {c.name for c in contracts}
    assert table_names == {"customers", "orders", "order_items"}

    # verify orders contract columns and PK/FK
    orders_contract = next(c for c in contracts if c.name == "orders")
    assert orders_contract.row_count == 1
    assert orders_contract.role in ("fact", "unknown")

    col_map = {col.name: col for col in orders_contract.columns}
    assert col_map["order_id"].is_pk is True
    assert col_map["customer_id"].is_fk is True
    assert col_map["total_amount"].data_type.upper() == "REAL"

    # verify foreign key relationship extracted
    assert len(orders_contract.relationships) >= 1
    rel = orders_contract.relationships[0]
    assert rel.source_column == "customer_id"
    assert rel.target_table == "customers"
    assert rel.target_column == "customer_id"


def test_sqlite_adapter_integrates_with_graph_and_solver(sqlite_conn: sqlite3.Connection) -> None:
    adapter = SQLiteAdapter(sqlite_conn)
    contracts = adapter.extract_contracts()

    # load extracted contracts into SchemaGraph
    graph = SchemaGraph()
    graph.load_tables(contracts)

    # find join path between order_items and customers (2 hops)
    solver = SteinerJoinSolver(graph)
    join_tree = solver.solve(["order_items", "customers"])

    sql = join_tree.to_sql_from_clause()
    assert "orders" in sql
    assert "customers" in sql
    assert "order_items" in sql


def test_mssql_adapter_builds_contracts_from_metadata() -> None:
    from schema_compass.dialects.mssql import MSSQLAdapter

    mock_tables = [
        {"schema_name": "dbo", "table_name": "FactInternetSales", "row_count": 60398},
        {"schema_name": "dbo", "table_name": "DimCustomer", "row_count": 18484},
    ]
    mock_columns = [
        {
            "schema_name": "dbo",
            "table_name": "FactInternetSales",
            "column_name": "SalesOrderNumber",
            "data_type": "nvarchar",
            "is_nullable": False,
            "is_pk": True,
            "is_fk": False,
        },
        {
            "schema_name": "dbo",
            "table_name": "FactInternetSales",
            "column_name": "CustomerKey",
            "data_type": "int",
            "is_nullable": False,
            "is_pk": False,
            "is_fk": True,
        },
        {
            "schema_name": "dbo",
            "table_name": "FactInternetSales",
            "column_name": "SalesAmount",
            "data_type": "money",
            "is_nullable": False,
            "is_pk": False,
            "is_fk": False,
        },
        {
            "schema_name": "dbo",
            "table_name": "DimCustomer",
            "column_name": "CustomerKey",
            "data_type": "int",
            "is_nullable": False,
            "is_pk": True,
            "is_fk": False,
        },
        {
            "schema_name": "dbo",
            "table_name": "DimCustomer",
            "column_name": "LastName",
            "data_type": "nvarchar",
            "is_nullable": True,
            "is_pk": False,
            "is_fk": False,
        },
    ]
    mock_fks = [
        {
            "fk_name": "FK_FactInternetSales_DimCustomer",
            "from_schema": "dbo",
            "from_table": "FactInternetSales",
            "from_column": "CustomerKey",
            "to_schema": "dbo",
            "to_table": "DimCustomer",
            "to_column": "CustomerKey",
        }
    ]

    contracts = MSSQLAdapter.build_from_catalog_rows(
        tables=mock_tables, columns=mock_columns, foreign_keys=mock_fks
    )
    assert len(contracts) == 2

    sales = next(c for c in contracts if c.name == "FactInternetSales")
    assert sales.role == "fact"
    assert sales.row_count == 60398
    assert len(sales.relationships) == 1
    assert sales.relationships[0].target_table == "DimCustomer"

    customer = next(c for c in contracts if c.name == "DimCustomer")
    assert customer.role == "dimension"


def test_postgres_adapter_builds_contracts_from_metadata() -> None:
    from schema_compass.dialects.postgres import PostgresAdapter

    mock_tables = [
        {"schema_name": "public", "table_name": "orders"},
        {"schema_name": "public", "table_name": "users"},
    ]
    mock_columns = [
        {
            "schema_name": "public",
            "table_name": "orders",
            "column_name": "id",
            "data_type": "bigint",
            "is_nullable": False,
            "is_pk": True,
            "is_fk": False,
        },
        {
            "schema_name": "public",
            "table_name": "orders",
            "column_name": "user_id",
            "data_type": "integer",
            "is_nullable": False,
            "is_pk": False,
            "is_fk": True,
        },
        {
            "schema_name": "public",
            "table_name": "orders",
            "column_name": "amount",
            "data_type": "numeric",
            "is_nullable": False,
            "is_pk": False,
            "is_fk": False,
        },
        {
            "schema_name": "public",
            "table_name": "users",
            "column_name": "id",
            "data_type": "integer",
            "is_nullable": False,
            "is_pk": True,
            "is_fk": False,
        },
        {
            "schema_name": "public",
            "table_name": "users",
            "column_name": "username",
            "data_type": "varchar",
            "is_nullable": False,
            "is_pk": False,
            "is_fk": False,
        },
    ]
    mock_fks = [
        {
            "fk_name": "fk_orders_users",
            "from_schema": "public",
            "from_table": "orders",
            "from_column": "user_id",
            "to_schema": "public",
            "to_table": "users",
            "to_column": "id",
        }
    ]

    contracts = PostgresAdapter.build_from_catalog_rows(
        tables=mock_tables, columns=mock_columns, foreign_keys=mock_fks
    )
    assert len(contracts) == 2

    orders = next(c for c in contracts if c.name == "orders")
    assert orders.role == "fact"
    assert len(orders.relationships) == 1
    assert orders.relationships[0].target_table == "users"

    users = next(c for c in contracts if c.name == "users")
    assert users.role == "dimension"


def test_export_schema_to_json(tmp_path) -> None:
    import json
    import sqlite3

    from schema_compass.export import export_schema_to_json

    db_path = tmp_path / "sample.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE products (product_id INT PRIMARY KEY, title TEXT)")
    conn.close()

    out_file = tmp_path / "exported.json"
    export_schema_to_json(source_type="sqlite", path=str(db_path), output_path=str(out_file))

    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["name"] == "products"
