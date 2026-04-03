"""Shared FastAPI dependencies for authentication, database access, and pagination."""

from fastapi import Depends, Query, Request

from djehuty.api.exceptions import AuthorizationError


def get_db(request: Request):
    """Return the shared SparqlInterface database instance."""
    return request.app.state.db


def get_token(request: Request) -> str | None:
    """Extract session token from cookie or Authorization header."""
    token = request.cookies.get("djehuty_session")
    if token is not None:
        return token

    auth = request.headers.get("Authorization", "")
    if auth.startswith("token "):
        return auth[6:]

    return None


def get_current_account(
    db=Depends(get_db),
    token: str | None = Depends(get_token),
) -> dict | None:
    """Resolve the authenticated account from the session token.

    Returns the account dict or None if not authenticated.
    """
    if token is None:
        return None
    return db.account_by_session_token(token)


def require_auth(account: dict | None = Depends(get_current_account)) -> dict:
    """Dependency that enforces authentication.

    Raises AuthorizationError if no valid session is found.
    """
    if account is None:
        raise AuthorizationError()
    return account


def pagination_params(
    page: int | None = Query(None, ge=1, description="Page number (1-based). Mutually exclusive with offset."),
    page_size: int | None = Query(None, ge=1, le=1000, description="Number of items per page. Used with `page`."),
    limit: int | None = Query(None, ge=1, le=1000, description="Maximum number of results to return."),
    offset: int | None = Query(None, ge=0, description="Number of results to skip."),
) -> dict:
    """Parse pagination parameters matching the legacy API behavior.

    Supports two styles:
    - ``page`` + ``page_size`` (1-based page numbering)
    - ``limit`` + ``offset`` (direct control)
    """
    if page is not None:
        effective_page_size = page_size if page_size is not None else 10
        return {
            "limit": effective_page_size,
            "offset": (page - 1) * effective_page_size,
        }

    return {
        "limit": limit if limit is not None else 10,
        "offset": offset if offset is not None else 0,
    }
