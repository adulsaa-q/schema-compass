"""Tests for Mermaid ERD Generator."""

from schema_compass.models import ColumnInfo, Relationship, TableContract
from schema_compass.profiler.erd import generate_mermaid_erd


def test_generate_mermaid_erd_syntax() -> None:
    customers = TableContract(
        name="customers",
        columns=[
            ColumnInfo(name="customer_id", data_type="INT", is_pk=True, nullable=False),
            ColumnInfo(name="name", data_type="VARCHAR(100)", nullable=False),
        ],
    )
    orders = TableContract(
        name="orders",
        columns=[
            ColumnInfo(name="order_id", data_type="INT", is_pk=True, nullable=False),
            ColumnInfo(name="customer_id", data_type="INT", is_fk=True, nullable=False),
            ColumnInfo(name="total", data_type="DECIMAL(10,2)"),
        ],
        relationships=[
            Relationship(
                source_table="orders",
                source_column="customer_id",
                target_table="customers",
                target_column="customer_id",
            )
        ],
    )

    erd = generate_mermaid_erd([customers, orders])
    assert "erDiagram" in erd
    assert "customers {" in erd
    assert "INT customer_id PK" in erd
    assert "orders {" in erd
    assert "INT customer_id FK" in erd
    assert "orders }o--|| customers : customer_id" in erd


def test_generate_mermaid_erd_empty() -> None:
    erd = generate_mermaid_erd([])
    assert "erDiagram" in erd
