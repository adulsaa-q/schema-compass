from typing import Protocol

from schema_compass.models import TableContract


class DialectAdapter(Protocol):
    """Protocol for database metadata extraction adapters."""

    def extract_contracts(self) -> list[TableContract]:
        """Extract schema metadata and return a list of TableContract models."""
        ...
