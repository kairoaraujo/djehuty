"""Route-parity guardrail for the FastAPI migration.

The migration goal is that the legacy ``djehuty.web.wsgi`` application can be
retired once the new ``djehuty.api`` package serves the same API surface. This
test compares the two route tables structurally so that:

* nothing in the new API exposes a /v2 or /v3 path the legacy app never had
  (no accidental new surface during an AS-IS migration), and
* every legacy /v2 or /v3 path is covered by the new API -- except the paths
  explicitly listed in ``KNOWN_GAPS`` below, which are not yet ported.

Scope & limits:
* Path-structural only. Parameter *names* are collapsed (``{}``) so
  ``/articles/<id>`` and ``/articles/{dataset_id}`` compare equal. HTTP
  *methods* are NOT compared here -- the legacy route table is method-agnostic
  (methods are enforced inside each handler); per-method behaviour is covered
  by the API contract suite (tests/e2e/tests/api).
* Only /v2 and /v3 are in scope. Legacy UI/compat routes are out of scope for
  this migration phase.

When a KNOWN_GAPS entry is implemented, remove it here -- the test fails if a
listed gap is actually covered, so the allowlist cannot rot.
"""

import importlib
import importlib.util
import re
from pathlib import Path

# Legacy /v2 or /v3 paths not yet ported to djehuty.api. Keep each line
# annotated with what it is so the backlog is self-documenting.
KNOWN_GAPS: set[str] = {
    # GET single dataset author; legacy api_v3_dataset_authors serves both
    # /authors and /authors/<author_uuid> from one handler.
    "/v3/datasets/{}/authors/{}",
}


def _normalize(path: str) -> str:
    """Collapse path params (Werkzeug <..> and FastAPI {..}) to {} and strip
    a trailing slash, so only the structural shape is compared."""
    path = re.sub(r"<[^>]+>", "{}", path)
    path = re.sub(r"\{[^}]+\}", "{}", path)
    return path.rstrip("/") or "/"


def _legacy_api_routes() -> set[str]:
    """Normalized /v2 and /v3 paths from the legacy ``R("...")`` route table."""
    # Locate wsgi.py without importing/executing it (djehuty.web is a namespace
    # package, so its __file__ is None).
    wsgi_path = Path(importlib.util.find_spec("djehuty.web.wsgi").origin)
    wsgi_src = wsgi_path.read_text(encoding="utf-8")
    routes = {_normalize(m) for m in re.findall(r'R\("([^"]+)"', wsgi_src)}
    return {p for p in routes if p.startswith(("/v2", "/v3"))}


def _fastapi_api_routes() -> set[str]:
    """Normalized /v2 and /v3 paths from the FastAPI routers.

    This build uses lazy router inclusion (_IncludedRouter), so we descend the
    include tree accumulating prefixes rather than reading a flat app.routes.
    """
    v2 = importlib.import_module("djehuty.api.v2.router").router
    v3 = importlib.import_module("djehuty.api.v3.router").router

    collected: set[str] = set()

    def walk(router, base: str) -> None:
        for route in router.routes:
            include_context = getattr(route, "include_context", None)
            if include_context is not None:
                sub = include_context.included_router
                walk(sub, base + (getattr(include_context, "prefix", "") or ""))
                continue
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if path and methods:
                collected.add(_normalize(base + path))

    walk(v2, "")
    walk(v3, "")
    return {p for p in collected if p.startswith(("/v2", "/v3"))}


def test_no_unexpected_new_api_surface():
    """The new API must not expose a /v2 or /v3 path the legacy app lacked."""
    extra = _fastapi_api_routes() - _legacy_api_routes()
    assert not extra, (
        "FastAPI exposes /v2 or /v3 paths with no legacy equivalent "
        f"(AS-IS migration should not add surface): {sorted(extra)}"
    )


def test_legacy_api_routes_are_covered_except_known_gaps():
    """Every legacy /v2 or /v3 path is covered, except the tracked KNOWN_GAPS."""
    missing = _legacy_api_routes() - _fastapi_api_routes()
    untracked = missing - KNOWN_GAPS
    assert not untracked, (
        "Legacy /v2 or /v3 paths are not covered by the new API and are not "
        f"tracked in KNOWN_GAPS: {sorted(untracked)}"
    )


def test_known_gaps_are_still_actually_gaps():
    """A KNOWN_GAPS entry that is now covered must be removed from the list."""
    covered = _fastapi_api_routes()
    closed = {gap for gap in KNOWN_GAPS if gap in covered}
    assert not closed, (
        "These KNOWN_GAPS are now implemented -- remove them from the "
        f"allowlist: {sorted(closed)}"
    )
