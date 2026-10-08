from typing import Literal

from schema_compass.models import ColumnInfo, TableContract
from schema_compass.search import tokenize

Role = Literal["fact", "dimension", "bridge", "unknown"]

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


ADDITIVE_MEASURE_WORDS = frozenset(
    {
        "amount",
        "qty",
        "quantity",
        "total",
        "revenue",
        "sales",
        "balance",
        "tax",
        "discount",
        "freight",
    }
)
TEMPORAL_TYPE_KEYWORDS = ("date", "time")
TEMPORAL_NAME_WORDS = frozenset({"date", "time", "timestamp", "datetime", "at"})


def _canonical_names(clean_name: str) -> set[str]:
    """The name plus its plural, so `Invoice` is recognised like `invoices`."""
    plurals = {clean_name + "s", clean_name + "es"}
    if clean_name.endswith("y"):
        plurals.add(clean_name[:-1] + "ies")
    return {clean_name} | plurals


def _role_from_name_or_schema(table_name: str, columns: list[ColumnInfo]) -> Role | None:
    """Roles a table settles by itself: explicit prefixes, canonical names, SCD or key-only shape."""
    clean_name = table_name.lower().split(".")[-1]
    names = _canonical_names(clean_name)

    # naming prefix or canonical domain name is primary signal
    if clean_name.startswith(FACT_PREFIXES) or names & FACT_NAMES:
        return "fact"
    if clean_name.startswith(DIM_PREFIXES) or names & DIM_NAMES:
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
    return None


def _measure_columns(columns: list[ColumnInfo]) -> list[ColumnInfo]:
    return [
        c
        for c in columns
        if any(m in c.name.lower() for m in MEASURE_NAME_KEYWORDS)
        or any(t in c.data_type.lower() for t in MEASURE_TYPE_KEYWORDS)
    ]


def classify_table_role(
    table_name: str,
    columns: list[ColumnInfo],
    row_count: int = 0,
    outgoing_fks: int = 0,
) -> Role:
    """First-pass role of one table. Use `refine_roles` once all tables are known."""
    settled = _role_from_name_or_schema(table_name, columns)
    if settled:
        return settled

    # multiple outgoing FKs with numeric measures indicates a fact table
    if outgoing_fks >= 2 and len(_measure_columns(columns)) >= 1:
        return "fact"

    # tables with descriptive text attributes default to dimension
    if len(columns) > 0:
        return "dimension"

    return "unknown"


def _is_temporal(column: ColumnInfo) -> bool:
    return any(k in column.data_type.lower() for k in TEMPORAL_TYPE_KEYWORDS) or bool(
        TEMPORAL_NAME_WORDS & set(tokenize(column.name))
    )


def _has_additive_measure(columns: list[ColumnInfo]) -> bool:
    return any(ADDITIVE_MEASURE_WORDS & set(tokenize(c.name)) for c in columns)


def refine_roles(contracts: list[TableContract]) -> list[TableContract]:
    """Assign roles using the foreign-key graph.

    A table with measures and several foreign keys is only a fact if nothing else points at it.
    `Track` (price, three foreign keys) is referenced by `InvoiceLine`, so it is a dimension.
    A dated table with an additive total, such as an invoice header, is also a fact.
    Roles settled by name or schema (prefixes, canonical names, SCD columns, bridge shape) stay.
    """
    tables = {c.name.lower().split(".")[-1] for c in contracts}
    settled = {c.name: _role_from_name_or_schema(c.name, c.columns) for c in contracts}

    def targets(c: TableContract) -> set[str]:
        own = c.name.lower().split(".")[-1]
        found = {r.target_table.lower().split(".")[-1] for r in c.relationships}
        return {t for t in found if t != own and t in tables}

    # who references each table; bridges only record membership, so they do not count
    referenced_by: dict[str, set[str]] = {t: set() for t in tables}
    for c in contracts:
        if settled[c.name] == "bridge":
            continue
        for target in targets(c):
            referenced_by[target].add(c.name.lower().split(".")[-1])

    refined: list[TableContract] = []
    for c in contracts:
        role = settled[c.name]
        if role is None:
            out = targets(c)
            referenced = referenced_by[c.name.lower().split(".")[-1]]
            if (
                not referenced
                and len(out) >= 2
                and _measure_columns(c.columns)
                or (
                    out
                    and _has_additive_measure(c.columns)
                    and any(_is_temporal(col) for col in c.columns)
                )
            ):
                role = "fact"
            else:
                role = "dimension" if c.columns else "unknown"
        refined.append(c.model_copy(update={"role": role}))
    return refined
