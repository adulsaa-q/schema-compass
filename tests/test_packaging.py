"""Guards against shipping a package that only works inside the source checkout."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "schema_compass"


def test_src_never_imports_from_tests() -> None:
    offenders: list[str] = []
    for py in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "tests":
                offenders.append(f"{py.relative_to(SRC)}:{node.lineno}")
            elif isinstance(node, ast.Import):
                offenders += [
                    f"{py.relative_to(SRC)}:{node.lineno}"
                    for a in node.names
                    if a.name.split(".")[0] == "tests"
                ]
    assert not offenders, f"src/ must not depend on tests/: {offenders}"


def test_sample_source_loads_without_tests_package() -> None:
    from schema_compass.server import load_contracts_from_source

    contracts = load_contracts_from_source("sample")
    assert contracts


def test_version_comes_from_package_metadata() -> None:
    from importlib.metadata import version

    import schema_compass

    assert schema_compass.__version__ == version("schema-compass")


def test_server_reports_its_version() -> None:
    import schema_compass
    from schema_compass.server import create_server

    assert create_server(contracts=[]).version == schema_compass.__version__
