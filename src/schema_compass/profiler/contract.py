from typing import Literal

from schema_compass.models import TableContract


def format_contract(contract: TableContract, mode: Literal["compact", "full"] = "compact") -> str:
    # renders token-efficient markdown contract for LLM context injection
    rows_str = f"{contract.row_count:,}" if contract.row_count else "0"
    role_str = contract.role.lower()

    lines = [f"### table: {contract.full_name} [{role_str} | {rows_str} rows]"]

    if mode == "full" and contract.description:
        lines.append(f"Description: {contract.description}")

    lines.append("Columns:")
    for col in contract.columns:
        flags = []
        if col.is_pk:
            flags.append("PK")
        if col.is_fk:
            # Inline FK target in compact format to prevent hallucinated joins
            fk_targets = [
                f"{rel.target_table}.{rel.target_column}"
                for rel in contract.relationships
                if rel.source_column == col.name
            ]
            if fk_targets:
                flags.append(f"FK -> {', '.join(fk_targets)}")
            else:
                flags.append("FK")
        if not col.nullable:
            flags.append("NOT NULL")

        flag_str = f" ({', '.join(flags)})" if flags else ""

        extras = []
        if col.null_rate > 0.0:
            extras.append(f"null: {col.null_rate:.1%}")
        if col.sample_values:
            samples_repr = ", ".join(repr(s) for s in col.sample_values[:3])
            extras.append(f"samples: [{samples_repr}]")

        extra_str = f" [{', '.join(extras)}]" if extras else ""
        lines.append(f"- {col.name}: {col.data_type}{flag_str}{extra_str}")

    if mode == "full" and contract.relationships:
        lines.append("Relationships:")
        for rel in contract.relationships:
            lines.append(
                f"- {rel.source_column} -> {rel.target_table}.{rel.target_column} ({rel.relationship_type})"
            )

    return "\n".join(lines)
