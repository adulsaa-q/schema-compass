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


class SchemaCompassError(Exception):
    """Base exception for all schema-compass domain, graph, and safety errors."""


class DisconnectedGraphError(SchemaCompassError):
    """Raised when two or more requested tables cannot be connected."""


class DialectAdapterError(SchemaCompassError):
    """Raised when database dialect metadata extraction fails."""
