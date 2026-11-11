"""Structural rules from CLAUDE.md, enforced.

- backend/scheduler/, orbits/pass_prediction.py and fleet/config_loader.py import no framework
  (FastAPI, SQLAlchemy, Alembic, Pydantic, Typer) and nothing from `ephemera` that would.
- Only the `fetch-orbital-data` CLI command loads `orbits.celestrak_client`.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
FRAMEWORKS = {"fastapi", "starlette", "sqlalchemy", "alembic", "pydantic", "pydantic_settings", "typer"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


PURE_FILES = [
    *sorted((BACKEND / "scheduler").rglob("*.py")),
    BACKEND / "ephemera" / "orbits" / "pass_prediction.py",
    BACKEND / "ephemera" / "fleet" / "config_loader.py",
    BACKEND / "ephemera" / "downlink" / "simulation.py",
]


@pytest.mark.parametrize("path", PURE_FILES, ids=lambda p: str(p.relative_to(BACKEND)))
def test_pure_modules_import_no_framework(path):
    roots = {name.split(".")[0] for name in _imports(path)}
    assert not roots & FRAMEWORKS, f"{path.name} imports {roots & FRAMEWORKS}"
    assert "ephemera" not in roots, f"{path.name} imports from ephemera"


def _loaded_modules(*modules: str) -> set[str]:
    code = "import sys\n" + "".join(f"import {m}\n" for m in modules) + "print('\\n'.join(sys.modules))"
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, check=True)
    return set(out.stdout.split())


def test_pure_modules_pull_in_no_framework_at_runtime():
    loaded = _loaded_modules(
        "scheduler", "ephemera.orbits.pass_prediction", "ephemera.fleet.config_loader", "ephemera.downlink.simulation"
    )
    assert not {m.split(".")[0] for m in loaded} & FRAMEWORKS


def test_only_the_fetch_command_loads_the_celestrak_client():
    # Everything except the CLI's fetch command. When the API and scheduler code arrive they
    # are added here.
    loaded = _loaded_modules(
        "ephemera.cli",
        "ephemera.orbits.passes_service",
        "ephemera.orbits.report",
        "ephemera.fleet.seed",
        "ephemera.fleet.lookup",
        "ephemera.downlink.adapters",
        "ephemera.downlink.runs",
        "ephemera.downlink.simulation",
        "scheduler",
    )
    assert "ephemera.orbits.celestrak_client" not in loaded


def test_no_module_imports_celestrak_client_except_the_cli():
    offenders = []
    for path in [*(BACKEND / "ephemera").rglob("*.py"), *(BACKEND / "scheduler").rglob("*.py")]:
        if path.name in ("cli.py", "celestrak_client.py"):
            continue
        if any("celestrak_client" in name for name in _imports(path)):
            offenders.append(str(path.relative_to(BACKEND)))
        elif "celestrak_client" in path.read_text():
            # catches `from ephemera.orbits import celestrak_client`
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom) and any(a.name == "celestrak_client" for a in node.names):
                    offenders.append(str(path.relative_to(BACKEND)))
    assert offenders == []
