"""Mermaid Entity-Relationship Diagram (ERD) Generator."""

import re

from schema_compass.models import TableContract


def sanitize_mermaid_name(name: str) -> str:
    """Sanitize table or type name for Mermaid syntax."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def generate_mermaid_erd(tables: list[TableContract]) -> str:
    """Generate a Mermaid erDiagram string from a list of TableContract models."""
    if not tables:
        return "erDiagram\n"

    lines = ["erDiagram"]
    rendered_relationships: set[tuple[str, str, str]] = set()

    # Render table definitions with columns and keys
    for table in tables:
        t_name = sanitize_mermaid_name(table.name)
        lines.append(f"    {t_name} {{")
        for col in table.columns:
            # Clean data type for Mermaid (remove parentheses, e.g. VARCHAR(50) -> VARCHAR_50)
            clean_type = sanitize_mermaid_name(col.data_type) or "TEXT"
            clean_col = sanitize_mermaid_name(col.name)
            flags = []
            if col.is_pk:
                flags.append("PK")
            if col.is_fk:
                flags.append("FK")
            flag_str = f" {' '.join(flags)}" if flags else ""
            lines.append(f"        {clean_type} {clean_col}{flag_str}")
        lines.append("    }")

    # Render relationship lines
    for table in tables:
        src = sanitize_mermaid_name(table.name)
        for rel in table.relationships:
            tgt = sanitize_mermaid_name(rel.target_table)
            rel_label = sanitize_mermaid_name(rel.source_column)
            edge_key = (src, tgt, rel_label)
            if edge_key not in rendered_relationships:
                rendered_relationships.add(edge_key)
                lines.append(f"    {src} }}o--|| {tgt} : {rel_label}")

    return "\n".join(lines)
