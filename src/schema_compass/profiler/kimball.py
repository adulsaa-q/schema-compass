from typing import Literal

from schema_compass.models import ColumnInfo

FACT_PREFIXES = ("fact_", "fct_", "f_", "fact")
DIM_PREFIXES = ("dim_", "d_", "dim")
BRIDGE_PREFIXES = ("bridge_", "map_", "xref_", "br_", "bridge")


FACT_NAMES = {
    "orders",
    "order_items",
    "sales",
    "invoices",
    "transactions",
    "events",
    "logs",
    "snapshots",
    "shipments",
    "payments",
}
DIM_NAMES = {
    "customers",
    "users",
    "products",
    "categories",
    "regions",
    "stores",
    "dates",
    "calendar",
    "suppliers",
    "employees",
}

SCD_COLUMNS = {"is_current", "valid_from", "valid_to", "start_date", "end_date", "row_is_current"}


MEASURE_TYPE_KEYWORDS = ("decimal", "numeric", "money", "float", "double", "real")
MEASURE_NAME_KEYWORDS = (
    "amount",
    "qty",
    "quantity",
    "price",
    "cost",
    "revenue",
    "sales",
    "total",
    "tax",
    "balance",
    "discount",
)


def classify_table_role(
    table_name: str,
    columns: list[ColumnInfo],
    row_count: int = 0,
    outgoing_fks: int = 0,
) -> Literal["fact", "dimension", "bridge", "unknown"]:
    clean_name = table_name.lower().split(".")[-1]

    # naming prefix or canonical domain name is primary signal
    if clean_name.startswith(FACT_PREFIXES) or clean_name in FACT_NAMES:
        return "fact"
    if clean_name.startswith(DIM_PREFIXES) or clean_name in DIM_NAMES:
        return "dimension"
    if clean_name.startswith(BRIDGE_PREFIXES):
        return "bridge"

    # SCD tracking columns identify Type 2 dimensions regardless of table name
    col_names = {c.name.lower() for c in columns}
    if any(scd in col_names for scd in SCD_COLUMNS):
        return "dimension"

    # bridge tables usually consist purely of composite foreign keys
    pk_fk_cols = [c for c in columns if c.is_pk and c.is_fk]
    if len(columns) <= 4 and len(pk_fk_cols) >= 2:
        return "bridge"

    # detect numeric measure columns
    measure_cols = [
        c
        for c in columns
        if any(m in c.name.lower() for m in MEASURE_NAME_KEYWORDS)
        or any(t in c.data_type.lower() for t in MEASURE_TYPE_KEYWORDS)
    ]

    # multiple outgoing FKs with numeric measures indicates a fact table
    if outgoing_fks >= 2 and len(measure_cols) >= 1:
        return "fact"

    # tables with descriptive text attributes default to dimension
    if len(columns) > 0:
        return "dimension"

    return "unknown"
