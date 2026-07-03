"""Account search endpoints for the v3 API."""

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from djehuty.api.dependencies import get_db, require_auth
from djehuty.api.models.common import ErrorResponse
from djehuty.api.v3._shared import _ok
from djehuty.web import formatter

router = APIRouter(tags=["V3 / Accounts"])

_ACCOUNT_EXAMPLE = {
    "id": None,
    "uuid": "84cae99f-a691-4af2-9d21-f5c0817c26df",
    "first_name": "Dev",
    "last_name": "User",
    "full_name": None,
    "email": "dev@djehuty.com",
    "is_active": True,
    "is_public": False,
    "job_title": None,
    "orcid_id": "",
}


@router.post(
    "/accounts/search",
    summary="Search accounts",
    description="Search for user accounts. Requires reviewer privileges.",
    responses={
        200: _ok("Matching accounts", [_ACCOUNT_EXAMPLE]),
        403: {"model": ErrorResponse},
    },
)
def search_accounts(
    body: dict = Body(
        ...,
        openapi_examples={
            "default": {
                "summary": "Search by name or email",
                "value": {"search_for": "dev", "exclude": []},
            }
        },
    ),
    account=Depends(require_auth),
    db=Depends(get_db),
):
    # Legacy reads the filter dict from the JSON body (POST).
    if not isinstance(body, dict):
        body = {}
    # AS-IS (#111): legacy reads `exclude` via array_value(required=False),
    # which returns None when the field is absent, then evaluates
    # `account["uuid"] in exclude` -> `... in None` -> TypeError. That is not
    # caught by legacy's `except (ValidationException, KeyError)`, so it
    # propagates -> HTTP 500 whenever the search matches at least one account.
    # Reproduce faithfully: no guard on `exclude`.
    search_for = body.get("search_for")
    exclude = body.get("exclude")
    accounts = db.accounts(search_for=search_for, limit=5)
    for index, _ in enumerate(accounts):
        record = accounts[index]
        if record["uuid"] in exclude:
            accounts.pop(index)
    return JSONResponse(content=[formatter.format_account_details_record(r) for r in accounts])
