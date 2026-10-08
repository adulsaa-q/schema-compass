# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## What the SQL guard does and does not do

`ASTGuard` parses a query with `sqlglot` and rejects it unless it is a single read-only `SELECT`.
It is a defense-in-depth layer for queries written by an AI agent, not a replacement for database
permissions. **Run the database connection as a read-only user.** `execute_safe_query` currently
only validates and rewrites SQL; it does not execute it.

Blocked by default:

- anything but one `SELECT` statement (DDL, DML, `EXEC`, `COPY`, `ATTACH`, multi-statement);
- functions outside an allowlist (unknown functions are rejected, not just known-bad ones), plus a
  hard-deny list for file/OS access, sleeps and state changes (`nextval`, advisory locks, `lo_*`);
- reads of system catalogs (`sys.*`, `pg_catalog`, `pg_shadow`, `sqlite_master`, `mysql.*`, `master..`);
- table hints that take locks (`TABLOCKX`, `UPDLOCK`, `HOLDLOCK`, ...) and `OPTION (MAXRECURSION 0)`;
- recursive CTEs, unconstrained Cartesian joins, and queries over the join or nesting limits.

Opt in with `--allow-function NAME`, `--allow-recursive-cte`, `--allow-system-catalogs`
(or the matching `ASTGuard(...)` arguments). Hard-denied functions cannot be unlocked.

Known limits (not protected):

- Allowed functions can still be expensive. `generate_series(1, 1000000000)` passes, and a `LIMIT`
  does not stop the work when the query also has `ORDER BY` or an aggregate. Use a statement
  timeout on the database user.
- `NOLOCK` avoids blocking writers but can return uncommitted rows, so results may be inconsistent.
- Server version and session variables such as `@@version` are readable.
- The column-level PII filter is name-based (`salary`, `password`, ...) and will not catch a
  sensitive column with an innocent name.

## Reporting a Vulnerability

The `schema-compass` team takes the security of database connections, query parsing, and credential protection seriously.

If you believe you have found a security vulnerability (such as an AST safety bypass, SQL injection evasion, unauthorized data exfiltration, or remote code execution loophole), please follow coordinated vulnerability disclosure:

1. **Do not disclose the issue publicly.** Do not create public GitHub issues or discussions for sensitive security vulnerabilities.
2. **Submit a Private Vulnerability Report:**
   - Use GitHub's private vulnerability reporting feature via [Security Advisory](https://github.com/adulsaa-q/schema-compass/security/advisories/new).
   - Alternatively, email details to: `adulsaa.q@gmail.com` with the subject line `[SECURITY] schema-compass Vulnerability Report`.
3. **Include the Following Information:**
   - Affected component (e.g. `ast_guard.py`, `steiner_solver.py`, `server.py`).
   - Step-by-step reproduction instructions or proof-of-concept query.
   - Impact assessment (e.g., bypasses read-only lock, bypasses column DLP).

## Response Timeline

- **Acknowledgment:** Within 48 hours.
- **Triage & Assessment:** Within 5 business days.
- **Patch & Release:** Priority fix with a dedicated security advisory and CVE assignment where applicable.
