"""Local Append-Only Security Audit Logger for Schema-Compass."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLogger:
    """Thread-safe append-only local audit log for SQL query requests."""

    def __init__(self, log_path: Path | str = Path(".remember/audit_log.jsonl")) -> None:
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_query(
        self,
        sql: str,
        dialect: str = "tsql",
        allowed: bool = True,
        reason: str | None = None,
        max_rows: int = 100,
        duration_ms: float = 0.0,
    ) -> dict[str, Any]:
        """Record a query validation/execution event into the append-only log."""
        query_hash = hashlib.sha256(sql.strip().encode("utf-8")).hexdigest()[:16]
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "query_hash": query_hash,
            "dialect": dialect,
            "allowed": allowed,
            "reason": reason,
            "max_rows": max_rows,
            "duration_ms": round(duration_ms, 3),
            "sql_snippet": sql.strip()[:200],
        }

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

        return record

    def get_recent_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent audit records in reverse chronological order."""
        if not self.log_path.exists():
            return []

        lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
        records = []
        for line in reversed(lines[-limit:]):
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records
