"""Architectural guardrail for the FastAPI migration.

The new ``djehuty.api`` package is a framework-based, AS-IS reimplementation of
the endpoints currently served by the legacy ``djehuty.web.wsgi`` application.
A core goal of the migration is that ``wsgi.py`` can eventually be deleted in a
single, fearless step. That is only safe if the dependency direction stays
one-way: ``djehuty.api`` may depend on the framework-neutral shared core
(``djehuty.web.{validator,formatter,config,locks,s3,database}`` and
``djehuty.services``), but it must NEVER import the legacy WSGI app itself.

This test pins that invariant down so it cannot regress silently. If it fails,
a new-API module reached back into ``djehuty.web.wsgi`` -- move the needed code
into the neutral core (or ``djehuty.services``) instead.
"""

import ast
import importlib
from pathlib import Path

import pytest

LEGACY_WSGI_MODULE = "djehuty.web.wsgi"


def _api_python_files() -> list[Path]:
    api_pkg = importlib.import_module("djehuty.api")
    api_dir = Path(api_pkg.__file__).parent
    return sorted(api_dir.rglob("*.py"))


def _imported_modules(tree: ast.AST) -> set[str]:
    """Return the set of module names a parsed module imports."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is a relative import; djehuty.api never sits under
            # djehuty.web, so a relative import can't reach the legacy app.
            if node.level == 0 and node.module:
                modules.add(node.module)
    return modules


@pytest.mark.parametrize("path", _api_python_files(), ids=lambda p: p.name)
def test_api_module_does_not_import_legacy_wsgi(path: Path):
    """No module under djehuty.api may import the legacy WSGI application."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported = _imported_modules(tree)
    offending = {
        m for m in imported
        if m == LEGACY_WSGI_MODULE or m.startswith(LEGACY_WSGI_MODULE + ".")
    }
    assert not offending, (
        f"{path} imports the legacy WSGI app ({sorted(offending)}). "
        "djehuty.api must depend only on the framework-neutral shared core; "
        "move the needed code out of djehuty.web.wsgi instead."
    )
