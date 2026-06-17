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


def get_impersonator_token(request: Request) -> str | None:
    """Extract the impersonator session token, if any.

    Used by reviewer workflows where a reviewer "becomes" the depositor
    by visiting /review/goto-dataset/<id>, which sets this cookie.
    """
    return request.cookies.get("impersonator_djehuty_session")


def resolve_reviewer_context(
    db=Depends(get_db),
    impersonator_token: str | None = Depends(get_impersonator_token),
    submitter_token: str | None = Depends(get_token),
) -> dict:
    """Determine which account is invoking a reviewer action.

    Mirrors the legacy precedence: try the impersonator cookie first
    (set by /review/goto-dataset/<id>), then fall back to the regular
    session token. Raises ``AuthorizationError`` if neither token
    grants reviewer privileges.

    Returns a dict with keys:
        token: the token whose perms apply
        account: the account record for that token
        may_review_all: bool
        may_review_institution: bool
    """
    for token in (impersonator_token, submitter_token):
        if not token:
            continue
        if db.may_review(token) or db.may_review_institution(token):
            return {
                "token": token,
                "account": db.account_by_session_token(token),
                "may_review_all": bool(db.may_review(token)),
                "may_review_institution": bool(db.may_review_institution(token)),
            }
    raise AuthorizationError()


def require_admin(
    token: str | None = Depends(get_token),
    account: dict | None = Depends(get_current_account),
    db=Depends(get_db),
) -> dict:
    """Enforce administrator permissions on the calling account.

    Returns the account dict. Raises ``AuthorizationError`` if the session
    is unauthenticated, ``ForbiddenError`` if the token does not grant
    ``may_administer``.
    """
    from djehuty.api.exceptions import ForbiddenError

    if account is None or token is None:
        raise AuthorizationError()
    if not db.may_administer(token):
        raise ForbiddenError("Administrator permissions required.")
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
