# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

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
