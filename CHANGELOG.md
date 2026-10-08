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

### Security
- SQL guard now uses a function **allowlist**: unknown (non-standard) functions are rejected instead of
  passing unless named in a deny-list. This closed bypasses found by probing with real dialect syntax:
  `pg_ls_dir`, `lo_import`, `query_to_xml`, `nextval`, `pg_advisory_lock`, `zeroblob`/`randomblob`,
  `LOAD_FILE`, DuckDB `read_csv`/`read_parquet`, and SQL Server `fn_*`/user-defined table functions.
- Reads of system catalogs (`sys.*`, `pg_catalog`, `pg_shadow`, `sqlite_master`, `mysql.*`, `master..`)
  are blocked by default.
- Table hints that take locks (`TABLOCKX`, `UPDLOCK`, `HOLDLOCK`, ...) are rejected; only
  `NOLOCK`/`READUNCOMMITTED`/index hints pass. `OPTION (MAXRECURSION 0)` and recursive CTEs are blocked.
- New opt-ins: `ASTGuard(extra_allowed_functions=, allow_recursive_cte=, allow_system_catalogs=)` and CLI flags
  `--allow-function`, `--allow-recursive-cte`, `--allow-system-catalogs`. Hard-denied functions cannot be unlocked.
- Four-part names (linked servers) are blocked, and every part of a name is checked against the system
  catalog list. `OPTION (MAXRECURSION n)` must be a literal between 1 and 32767.
- A correlated join is only excused for table functions (`FROM t, json_each(t.j)`), not for subqueries,
  `LATERAL` or `CROSS APPLY`, which could be made to pass as a Cartesian product with a dummy reference.
- Join conditions are checked for substance, not just presence: `ON 1=1`, `ON TRUE`, `a.id = a.id`,
  `a.id = b.id OR 1=1`, `NOT (a.id = b.id)` and equalities hidden in subqueries no longer pass as
  "constrained". Range-only joins now need an equality on the key.
- Blocked: file paths as table names (DuckDB), `FOR UPDATE`/`FOR SHARE`/`LOCK IN SHARE MODE`, Oracle
  `dba_*`/`v$*` and the Snowflake `snowflake` database. Comments are stripped from the returned SQL.
- SECURITY.md now states what the guard does not protect against.

### Fixed (guard false positives)
- `SELECT ...; --` (trailing semicolon plus comment) was rejected as multi-statement.
- Correlated joins to table functions (`FROM t, json_each(t.j)`, `CROSS APPLY`) were rejected as Cartesian.

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
