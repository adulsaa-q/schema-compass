"""Sample enterprise relational schema fixtures for testing."""

from schema_compass.models import ColumnInfo, Relationship, TableContract

SAMPLE_TABLES: dict[str, TableContract] = {
    "orders": TableContract(
        name="orders",
        schema_name="dbo",
        row_count=500_000,
        role="fact",
        columns=[
            ColumnInfo(name="order_id", data_type="BIGINT", is_pk=True),
            ColumnInfo(name="customer_id", data_type="INT", is_fk=True),
            ColumnInfo(name="store_id", data_type="INT", is_fk=True),
            ColumnInfo(name="promotion_id", data_type="INT", is_fk=True, nullable=True),
            ColumnInfo(name="order_date", data_type="DATE"),
            ColumnInfo(name="total_amount", data_type="DECIMAL(12,2)"),
        ],
        relationships=[
            Relationship(
                source_table="orders",
                source_column="customer_id",
                target_table="customers",
                target_column="customer_id",
                relationship_type="declared_fk",
                weight=1.0,
            ),
            Relationship(
                source_table="orders",
                source_column="store_id",
                target_table="stores",
                target_column="store_id",
                relationship_type="declared_fk",
                weight=1.0,
            ),
            Relationship(
                source_table="orders",
                source_column="promotion_id",
                target_table="promotions",
                target_column="promotion_id",
                relationship_type="declared_fk",
                weight=1.2,
            ),
        ],
    ),
    "order_items": TableContract(
        name="order_items",
        schema_name="dbo",
        row_count=1_800_000,
        role="fact",
        columns=[
            ColumnInfo(name="order_item_id", data_type="BIGINT", is_pk=True),
            ColumnInfo(name="order_id", data_type="BIGINT", is_fk=True),
            ColumnInfo(name="product_id", data_type="INT", is_fk=True),
            ColumnInfo(name="quantity", data_type="INT"),
            ColumnInfo(name="unit_price", data_type="DECIMAL(10,2)"),
        ],
        relationships=[
            Relationship(
                source_table="order_items",
                source_column="order_id",
                target_table="orders",
                target_column="order_id",
                relationship_type="declared_fk",
                weight=1.0,
            ),
            Relationship(
                source_table="order_items",
                source_column="product_id",
                target_table="products",
                target_column="product_id",
                relationship_type="declared_fk",
                weight=1.0,
            ),
        ],
    ),
    "customers": TableContract(
        name="customers",
        schema_name="dbo",
        row_count=45_000,
        role="dimension",
        columns=[
            ColumnInfo(name="customer_id", data_type="INT", is_pk=True),
            ColumnInfo(name="region_id", data_type="INT", is_fk=True),
            ColumnInfo(name="customer_name", data_type="VARCHAR(100)"),
            ColumnInfo(name="segment", data_type="VARCHAR(20)"),
        ],
        relationships=[
            Relationship(
                source_table="customers",
                source_column="region_id",
                target_table="regions",
                target_column="region_id",
                relationship_type="declared_fk",
                weight=1.0,
            ),
        ],
    ),
    "regions": TableContract(
        name="regions",
        schema_name="dbo",
        row_count=20,
        role="dimension",
        columns=[
            ColumnInfo(name="region_id", data_type="INT", is_pk=True),
            ColumnInfo(name="country_id", data_type="INT", is_fk=True),
            ColumnInfo(name="region_name", data_type="VARCHAR(50)"),
        ],
        relationships=[
            Relationship(
                source_table="regions",
                source_column="country_id",
                target_table="countries",
                target_column="country_id",
                relationship_type="declared_fk",
                weight=1.0,
            ),
        ],
    ),
    "countries": TableContract(
        name="countries",
        schema_name="dbo",
        row_count=10,
        role="dimension",
        columns=[
            ColumnInfo(name="country_id", data_type="INT", is_pk=True),
            ColumnInfo(name="country_name", data_type="VARCHAR(50)"),
        ],
        relationships=[],
    ),
    "stores": TableContract(
        name="stores",
        schema_name="dbo",
        row_count=150,
        role="dimension",
        columns=[
            ColumnInfo(name="store_id", data_type="INT", is_pk=True),
            ColumnInfo(name="region_id", data_type="INT", is_fk=True),
            ColumnInfo(name="store_name", data_type="VARCHAR(100)"),
        ],
        relationships=[
            Relationship(
                source_table="stores",
                source_column="region_id",
                target_table="regions",
                target_column="region_id",
                relationship_type="declared_fk",
                weight=1.0,
            ),
        ],
    ),
    "products": TableContract(
        name="products",
        schema_name="dbo",
        row_count=3_500,
        role="dimension",
        columns=[
            ColumnInfo(name="product_id", data_type="INT", is_pk=True),
            ColumnInfo(name="category_id", data_type="INT", is_fk=True),
            ColumnInfo(name="supplier_id", data_type="INT", is_fk=True),
            ColumnInfo(name="product_name", data_type="VARCHAR(150)"),
            ColumnInfo(name="price", data_type="DECIMAL(10,2)"),
        ],
        relationships=[
            Relationship(
                source_table="products",
                source_column="category_id",
                target_table="categories",
                target_column="category_id",
                relationship_type="declared_fk",
                weight=1.0,
            ),
            Relationship(
                source_table="products",
                source_column="supplier_id",
                target_table="suppliers",
                target_column="supplier_id",
                relationship_type="declared_fk",
                weight=1.0,
            ),
        ],
    ),
    "categories": TableContract(
        name="categories",
        schema_name="dbo",
        row_count=40,
        role="dimension",
        columns=[
            ColumnInfo(name="category_id", data_type="INT", is_pk=True),
            ColumnInfo(name="category_name", data_type="VARCHAR(50)"),
        ],
        relationships=[],
    ),
    "suppliers": TableContract(
        name="suppliers",
        schema_name="dbo",
        row_count=80,
        role="dimension",
        columns=[
            ColumnInfo(name="supplier_id", data_type="INT", is_pk=True),
            ColumnInfo(name="country_id", data_type="INT", is_fk=True),
            ColumnInfo(name="supplier_name", data_type="VARCHAR(100)"),
        ],
        relationships=[
            Relationship(
                source_table="suppliers",
                source_column="country_id",
                target_table="countries",
                target_column="country_id",
                relationship_type="declared_fk",
                weight=1.0,
            ),
        ],
    ),
    "promotions": TableContract(
        name="promotions",
        schema_name="dbo",
        row_count=25,
        role="dimension",
        columns=[
            ColumnInfo(name="promotion_id", data_type="INT", is_pk=True),
            ColumnInfo(name="promo_code", data_type="VARCHAR(20)"),
            ColumnInfo(name="discount_pct", data_type="DECIMAL(5,2)"),
        ],
        relationships=[],
    ),
    "audit_logs": TableContract(
        name="audit_logs",
        schema_name="sys",
        row_count=100_000,
        role="fact",
        columns=[
            ColumnInfo(name="log_id", data_type="BIGINT", is_pk=True),
            ColumnInfo(name="action", data_type="VARCHAR(50)"),
            ColumnInfo(name="timestamp", data_type="DATETIME"),
        ],
        relationships=[],
    ),
}

SAMPLE_CONTRACTS: list[TableContract] = list(SAMPLE_TABLES.values())
