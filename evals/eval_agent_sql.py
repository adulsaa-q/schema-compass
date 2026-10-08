"""Ask Claude Code to write SQL for Chinook questions with and without schema-compass, then check the answers.

Needs the `claude` CLI, an API key (every run is billed), and the public Chinook SQLite file
(github.com/lerocha/chinook-database, Chinook_Sqlite.sqlite) or a larger database built from it with
evals/make_large_schema.py. Answers are run read-only and compared with reference queries.

    BENCH_DB=chinook.sqlite uv run python evals/eval_agent_sql.py all A_mcp,B_ddl
    BENCH_DB=large.sqlite BENCH_BUDGET=1.6 uv run python evals/eval_agent_sql.py q1_country_sales B_ddl

A_mcp: the model sees only the schema-compass tools. B_ddl: the model gets the full DDL in the prompt.
BENCH_BUDGET caps the cost of each run in USD (default 0.60; a 1,000 table DDL needs about 0.7).
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HERE = Path(tempfile.mkdtemp(prefix="agent_sql_"))
DB = Path(os.environ["BENCH_DB"]).resolve()
CLAUDE = shutil.which("claude")
OUT = HERE / os.environ.get("BENCH_RUNS", "runs")
OUT.mkdir(exist_ok=True)

QUESTIONS = {
    "q1_country_sales": (
        "Total invoice amount (Invoice.Total) per billing country. Return country and total.",
        "SELECT BillingCountry, SUM(Total) FROM Invoice GROUP BY BillingCountry",
    ),
    "q2_top_genres": (
        "The 5 genres with the highest revenue, where revenue is invoice line unit price times quantity. Return genre name and revenue.",
        "SELECT g.Name, SUM(il.UnitPrice*il.Quantity) r FROM InvoiceLine il JOIN Track t ON t.TrackId=il.TrackId JOIN Genre g ON g.GenreId=t.GenreId GROUP BY g.GenreId ORDER BY r DESC LIMIT 5",
    ),
    "q3_iron_maiden": (
        "Customers (first name, last name) who bought at least one track by the artist 'Iron Maiden'. Each customer once.",
        "SELECT DISTINCT c.FirstName, c.LastName FROM Customer c JOIN Invoice i ON i.CustomerId=c.CustomerId JOIN InvoiceLine il ON il.InvoiceId=i.InvoiceId JOIN Track t ON t.TrackId=il.TrackId JOIN Album a ON a.AlbumId=t.AlbumId JOIN Artist ar ON ar.ArtistId=a.ArtistId WHERE ar.Name='Iron Maiden'",
    ),
    "q4_avg_playlist": (
        "Average number of tracks per playlist, counting playlists that have no tracks as 0. Return one number.",
        "SELECT AVG(n) FROM (SELECT COUNT(pt.TrackId) n FROM Playlist p LEFT JOIN PlaylistTrack pt ON pt.PlaylistId=p.PlaylistId GROUP BY p.PlaylistId)",
    ),
    "q5_rep_revenue": (
        "Total invoice amount (Invoice.Total) handled per sales support representative (the employee assigned to the customer). Return the rep's first name, last name and the total.",
        "SELECT e.FirstName, e.LastName, SUM(i.Total) FROM Employee e JOIN Customer c ON c.SupportRepId=e.EmployeeId JOIN Invoice i ON i.CustomerId=c.CustomerId GROUP BY e.EmployeeId",
    ),
    "q6_fanout_trap": (
        "For each genre, the sum of Invoice.Total over the invoices that contain at least one track of that genre. Each invoice counts once per genre. Return genre name and the sum.",
        "SELECT g.Name, SUM(i.Total) FROM (SELECT DISTINCT il.InvoiceId, t.GenreId FROM InvoiceLine il JOIN Track t ON t.TrackId=il.TrackId) x JOIN Invoice i ON i.InvoiceId=x.InvoiceId JOIN Genre g ON g.GenreId=x.GenreId GROUP BY g.GenreId",
    ),
}


def ro():
    return sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)


def norm(rows):
    return sorted(tuple(round(v, 2) if isinstance(v, float) else v for v in r) for r in rows)


def ddl():
    with ro() as c:
        return "\n".join(
            r[0] + ";"
            for r in c.execute("select sql from sqlite_master where type='table' order by name")
        )


def cfg_file():
    p = HERE / "mcp.json"
    p.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "schema-compass": {
                        "command": "uv",
                        "args": [
                            "--directory",
                            str(REPO),
                            "run",
                            "schema-compass",
                            "--source",
                            "sqlite",
                            "--path",
                            str(DB),
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return p


def run(name, cond):
    q, _ = QUESTIONS[name]
    base = [
        "--model",
        "sonnet",
        "--output-format",
        "stream-json",
        "--verbose",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--max-budget-usd",
        os.environ.get("BENCH_BUDGET", "0.60"),
        "--strict-mcp-config",
        "--tools",
        "",
        "--setting-sources",
        "",
    ]
    if cond == "A_mcp":
        prompt = (
            "Write one SQLite query for the Chinook database. You cannot see the database, so use the schema-compass tools "
            "to find the tables, columns and joins you need, then check the final query with execute_safe_query (dialect sqlite). "
            "Reply with only the final SQL in one ```sql block.\n\nQuestion: " + q
        )
        extra = [
            "--mcp-config",
            str(cfg_file()),
            "--allowedTools",
            "mcp__schema-compass__search_catalog,mcp__schema-compass__get_join_tree,mcp__schema-compass__get_table_contract,mcp__schema-compass__execute_safe_query,mcp__schema-compass__get_schema_diagram,mcp__schema-compass__explain_metric",
            "--max-turns",
            "12",
        ]
    else:
        prompt = (
            "Write one SQLite query for this database. Reply with only the final SQL in one ```sql block.\n\nSchema:\n"
            + ddl()
            + "\n\nQuestion: "
            + q
        )
        extra = ["--max-turns", "3"]
    t = time.time()
    p = subprocess.run(
        [CLAUDE, "-p", *base, *extra],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(HERE),
        timeout=300,
        check=False,  # a failed run is recorded as an error result, not raised
    )
    dt = time.time() - t
    events = []
    for line in p.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # the CLI also prints non-JSON progress lines
    j = next((e for e in reversed(events) if e.get("type") == "result"), None) or {
        "result": "",
        "is_error": True,
        "stderr": p.stderr[-500:],
        "stdout": p.stdout[-500:],
    }
    tools = [
        b["name"].replace("mcp__schema-compass__", "")
        for e in events
        if e.get("type") == "assistant"
        for b in e.get("message", {}).get("content", [])
        if isinstance(b, dict) and b.get("type") == "tool_use"
    ]
    (OUT / f"{name}__{cond}.json").write_text(
        json.dumps({**j, "tools_called": tools}, indent=1), encoding="utf-8"
    )
    m = re.search(r"```sql\s*(.*?)```", j.get("result", ""), re.DOTALL)
    sql = m.group(1).strip().rstrip(";") if m else None
    ok, note = False, ""
    if sql is None:
        note = "no sql block"
    else:
        try:
            with ro() as c:
                got = norm(c.execute(sql).fetchall())
                want = norm(c.execute(QUESTIONS[name][1]).fetchall())
            ok = got == want
            note = "" if ok else f"rows {len(got)} vs {len(want)}"
        except sqlite3.Error as e:
            note = f"sql error: {e}"[:80]
    u = j.get("usage", {})
    tokens = (
        u.get("input_tokens", 0)
        + u.get("cache_creation_input_tokens", 0)
        + u.get("cache_read_input_tokens", 0)
        + u.get("output_tokens", 0)
    )
    return {
        "q": name,
        "cond": cond,
        "ok": ok,
        "note": note,
        "turns": j.get("num_turns"),
        "cost": round(j.get("total_cost_usd") or 0, 4),
        "tokens": tokens,
        "secs": round(dt),
        "tools": tools,
        "sql": sql,
        "err": j.get("is_error"),
    }


if __name__ == "__main__":
    names = (
        sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] != "all" else list(QUESTIONS)
    )
    conds = sys.argv[2].split(",") if len(sys.argv) > 2 else ["A_mcp", "B_ddl"]
    results = []
    for n in names:
        for c in conds:
            r = run(n, c)
            results.append(r)
            print(json.dumps({k: v for k, v in r.items() if k != "sql"}), flush=True)
    (HERE / os.environ.get("BENCH_RESULTS", "results.json")).write_text(
        json.dumps(results, indent=1), encoding="utf-8"
    )
