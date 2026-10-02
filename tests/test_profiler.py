import pytest

from schema_compass.models import ColumnInfo, Relationship, TableContract
from schema_compass.profiler.contract import format_contract


@pytest.fixture
def sample_orders_contract() -> TableContract:
    return TableContract(
        name="orders",
        schema_name="dbo",
        row_count=1500000,
        role="fact",
        columns=[
            ColumnInfo(name="order_id", data_type="BIGINT", is_pk=True, nullable=False),
            ColumnInfo(
                name="customer_id",
                data_type="INT",
                is_fk=True,
                nullable=False,
                sample_values=[101, 102],
            ),
            ColumnInfo(name="order_date", data_type="DATE", nullable=False, null_rate=0.0),
            ColumnInfo(
                name="status",
                data_type="VARCHAR(20)",
                nullable=False,
                sample_values=["COMPLETED", "PENDING"],
            ),
            ColumnInfo(name="total_amount", data_type="DECIMAL(18,2)", nullable=False),
        ],
        relationships=[
            Relationship(
                source_table="orders",
                source_column="customer_id",
                target_table="customers",
                target_column="customer_id",
                relationship_type="declared_fk",
            )
        ],
        description="Core customer order transactions",
    )


def test_format_contract_compact(sample_orders_contract: TableContract) -> None:
    output = format_contract(sample_orders_contract, mode="compact")

    # verify compact header contains table role and row count
    assert "dbo.orders" in output
    assert "fact" in output
    assert "1,500,000" in output or "1500000" in output

    # verify key indicators and sample values appear
    assert "order_id" in output
    assert "PK" in output
    assert "customer_id" in output
    assert "FK" in output
    assert "COMPLETED" in output


def test_format_contract_compact_inlines_fk_target(sample_orders_contract: TableContract) -> None:
    output = format_contract(sample_orders_contract, mode="compact")
    assert "FK -> customers.customer_id" in output


def test_format_contract_full(sample_orders_contract: TableContract) -> None:
    output = format_contract(sample_orders_contract, mode="full")

    # verify description and relationships are displayed in full mode
    assert "Core customer order transactions" in output
    assert "customers" in output
    assert "declared_fk" in output


def test_classify_table_role_by_prefix() -> None:
    from schema_compass.profiler.kimball import classify_table_role

    assert classify_table_role("fact_orders", columns=[]) == "fact"
    assert classify_table_role("fct_sales", columns=[]) == "fact"
    assert classify_table_role("dim_customer", columns=[]) == "dimension"
    assert classify_table_role("bridge_user_group", columns=[]) == "bridge"


def test_classify_table_role_by_structure() -> None:
    from schema_compass.profiler.kimball import classify_table_role

    # fact table structure: multiple FKs, numeric metric columns, high row count
    order_cols = [
        ColumnInfo(name="order_id", data_type="BIGINT", is_pk=True),
        ColumnInfo(name="cust_id", data_type="INT", is_fk=True),
        ColumnInfo(name="prod_id", data_type="INT", is_fk=True),
        ColumnInfo(name="quantity", data_type="INT"),
        ColumnInfo(name="total_price", data_type="DECIMAL(12,2)"),
    ]
    assert (
        classify_table_role("orders", columns=order_cols, row_count=500000, outgoing_fks=2)
        == "fact"
    )

    # dimension table structure: single PK, descriptive text attributes, low row count
    cust_cols = [
        ColumnInfo(name="id", data_type="INT", is_pk=True),
        ColumnInfo(name="first_name", data_type="VARCHAR(50)"),
        ColumnInfo(name="last_name", data_type="VARCHAR(50)"),
        ColumnInfo(name="city", data_type="VARCHAR(50)"),
    ]
    assert (
        classify_table_role("customers", columns=cust_cols, row_count=2000, outgoing_fks=0)
        == "dimension"
    )

    # bridge table: pure composite foreign keys with no measure columns
    bridge_cols = [
        ColumnInfo(name="user_id", data_type="INT", is_pk=True, is_fk=True),
        ColumnInfo(name="role_id", data_type="INT", is_pk=True, is_fk=True),
    ]
    assert (
        classify_table_role("user_roles", columns=bridge_cols, row_count=10000, outgoing_fks=2)
        == "bridge"
    )

    # SCD Type 2 dimension: presence of tracking columns
    scd_cols = [
        ColumnInfo(name="emp_sk", data_type="INT", is_pk=True),
        ColumnInfo(name="emp_id", data_type="VARCHAR(10)"),
        ColumnInfo(name="department", data_type="VARCHAR(50)"),
        ColumnInfo(name="valid_from", data_type="DATETIME"),
        ColumnInfo(name="valid_to", data_type="DATETIME"),
        ColumnInfo(name="is_current", data_type="BOOLEAN"),
    ]
    assert classify_table_role("employees", columns=scd_cols) == "dimension"
