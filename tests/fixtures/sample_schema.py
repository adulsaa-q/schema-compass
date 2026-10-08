"""Re-export so existing tests and evals keep their import path."""

from schema_compass.sample_schema import SAMPLE_CONTRACTS, SAMPLE_TABLES

__all__ = ["SAMPLE_CONTRACTS", "SAMPLE_TABLES"]
