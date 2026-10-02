"""Tests for Security Audit Logger."""

import json
from pathlib import Path

import pytest

from schema_compass.safety.audit import AuditLogger


@pytest.fixture
def temp_audit_file(tmp_path: Path) -> Path:
    return tmp_path / "audit_log.jsonl"


def test_audit_logger_records_allowed_query(temp_audit_file: Path) -> None:
    logger = AuditLogger(log_path=temp_audit_file)
    logger.log_query(
        sql="SELECT id FROM users",
        dialect="postgres",
        allowed=True,
        max_rows=100,
        duration_ms=1.25,
    )

    assert temp_audit_file.exists()
    lines = temp_audit_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["allowed"] is True
    assert record["dialect"] == "postgres"
    assert "query_hash" in record
    assert record["reason"] is None


def test_audit_logger_records_blocked_query_with_reason(temp_audit_file: Path) -> None:
    logger = AuditLogger(log_path=temp_audit_file)
    logger.log_query(
        sql="DROP TABLE users",
        dialect="tsql",
        allowed=False,
        reason="Prohibited statement type: DROP",
    )

    lines = temp_audit_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["allowed"] is False
    assert "DROP" in record["reason"]


def test_audit_logger_fetches_recent_entries(temp_audit_file: Path) -> None:
    logger = AuditLogger(log_path=temp_audit_file)
    for i in range(5):
        logger.log_query(sql=f"SELECT {i}", dialect="sqlite", allowed=True)

    recent = logger.get_recent_logs(limit=3)
    assert len(recent) == 3
    # Most recent first
    assert recent[0]["query_hash"] is not None
