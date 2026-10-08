"""Core domain models for Schema-Compass."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ColumnInfo(BaseModel):
    """Metadata describing a single table column."""

    name: str
    data_type: str
    is_pk: bool = False
    is_fk: bool = False
    nullable: bool = True
    null_rate: float = 0.0
    sample_values: list[Any] = Field(default_factory=list)
    description: str | None = None


class Relationship(BaseModel):
    """A directed or bidirectional relationship edge between two tables."""

    source_table: str
    source_column: str
    target_table: str
    target_column: str
    relationship_type: Literal["declared_fk", "inferred_name", "inclusion_ind"] = "declared_fk"
    weight: float = 1.0


class TableContract(BaseModel):
    """Minimal Effective Context (MEC) representation of a table."""

    name: str
    schema_name: str = "dbo"
    row_count: int = 0
    role: Literal["fact", "dimension", "bridge", "unknown"] = "unknown"
    columns: list[ColumnInfo] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    description: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.schema_name}.{self.name}" if self.schema_name else self.name


class JoinStep(BaseModel):
    """A single join operation in an SQL join sequence."""

    from_table: str
    from_column: str
    to_table: str
    to_column: str
    join_type: Literal["JOIN", "LEFT JOIN"] = "JOIN"
    # many_to_one: from_table holds the foreign key (safe). one_to_many: to_table holds it, so each
    # from_table row can match several to_table rows and rows multiply.
    cardinality: Literal["many_to_one", "one_to_many", "unknown"] = "unknown"

    def to_sql(self) -> str:
        return f"{self.join_type} {self.to_table} ON {self.from_table}.{self.from_column} = {self.to_table}.{self.to_column}"


class JoinTree(BaseModel):
    """The computed join tree connecting terminal tables."""

    root_table: str
    steps: list[JoinStep] = Field(default_factory=list)
    tables_included: list[str] = Field(default_factory=list)
    total_weight: float = 0.0

    def to_sql_from_clause(self) -> str:
        """Render the complete FROM ... JOIN ... ON clause."""
        if not self.steps:
            return f"FROM {self.root_table}"
        lines = [f"FROM {self.root_table}"]
        for step in self.steps:
            lines.append(f"    {step.to_sql()}")
        return "\n".join(lines)

    def fan_out_warnings(self) -> list[str]:
        """Explain every step that walks from the "one" side to the "many" side of a key.

        Such a step repeats the rows joined so far, so SUM/COUNT over them overcounts.
        """
        children: dict[str, list[str]] = {}
        for step in self.steps:
            children.setdefault(step.from_table, []).append(step.to_table)

        def subtree(table: str) -> set[str]:
            found = {table}
            for child in children.get(table, []):
                found |= subtree(child)
            return found

        fan_steps = [s for s in self.steps if s.cardinality == "one_to_many"]
        warnings = []
        for step in fan_steps:
            repeated = [t for t in self.tables_included if t not in subtree(step.to_table)]
            warnings.append(
                f"{step.to_table} has many rows for each {step.from_table} row, so rows from "
                f"{', '.join(repeated)} repeat once per matching {step.to_table} row. "
                "SUM/COUNT over them will overcount; aggregate before joining or use "
                "COUNT(DISTINCT ...)."
            )
        if len(fan_steps) > 1:
            names = ", ".join(s.to_table for s in fan_steps)
            warnings.append(
                f"{names} are separate one-to-many branches and multiply each other; "
                "aggregate each branch on its own before combining them."
            )
        return warnings


class SchemaCompassError(Exception):
    """Base exception for all schema-compass domain, graph, and safety errors."""


class DisconnectedGraphError(SchemaCompassError):
    """Raised when two or more requested tables cannot be connected."""


class DialectAdapterError(SchemaCompassError):
    """Raised when database dialect metadata extraction fails."""
