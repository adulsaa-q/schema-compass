# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Fixed
- `search_catalog` returned nothing for any multi-word query ("invoice total", "customer email")
  because the whole phrase was matched as one substring. Queries are now split into words
  (camelCase, snake_case and `table.column` aware, common filler words and plurals handled) and
  ranked by how many words match; an exact table-name match ranks first. Found by running the
  server against the public Chinook database.

## [0.1.1] - 2026-10-08

### Fixed
- `--source sample` crashed when installed from a wheel because the package imported
  `tests.fixtures`. The sample schema now ships inside the package as `schema_compass.sample_schema`.

### Changed
- `__version__` is now read from package metadata (single source of truth in `pyproject.toml`),
  and the MCP `serverInfo.version` is no longer empty.
- README rewritten to match what the code does today: `execute_safe_query` validates and rewrites SQL
  (it does not run it), SQL Server / PostgreSQL / DuckDB are listed as roadmap items, and
  machine-specific paths and unreleased example files were removed.
- CI now runs `mypy --strict` on `src/`.

### Added
- `examples/sample_schema.json` for trying the server without a database.
- `tests/test_packaging.py` guarding against `src/` importing from `tests/`.

## [0.1.0] - 2026-10-02

- Initial release: schema graph with Steiner join solver, `sqlglot` AST safety guard,
  Kimball profiler, SQLite/MSSQL/Postgres metadata adapters, MCP server with six tools.
