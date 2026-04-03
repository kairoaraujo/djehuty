"""Simple reference-data endpoints: licenses, categories, account, OAuth."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from djehuty.web import formatter
from djehuty.api.dependencies import get_db, require_auth
from djehuty.api.exceptions import NotFoundError
from djehuty.api.models.licenses import License
from djehuty.api.models.categories import Category
from djehuty.api.models.common import ErrorResponse

router = APIRouter()


@router.get(
    "/licenses",
    response_model=list[License],
    summary="List all available licenses",
    description="Returns all licenses that can be applied to datasets and collections.",
    responses={
        200: {
            "description": "List of licenses",
            "content": {
                "application/json": {
                    "example": [
                        {"value": 1, "name": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/", "type": "data"},
                        {"value": 2, "name": "CC0 1.0", "url": "https://creativecommons.org/publicdomain/zero/1.0/", "type": "data"},
                    ]
                }
            },
        }
    },
    tags=["V2 / Licenses"],
)
def list_licenses(db=Depends(get_db)):
    records = db.licenses()
    return JSONResponse(
        content=[formatter.format_license_record(r) for r in records]
    )


@router.get(
    "/categories",
    response_model=list[Category],
    summary="List all research categories",
    description=(
        "Returns the full category taxonomy used for classifying datasets "
        "and collections. Categories are hierarchical — use `parent_id` to "
        "build a tree."
    ),
    responses={
        200: {
            "description": "List of categories",
            "content": {
                "application/json": {
                    "example": [
                        {"id": 1, "uuid": "abc-123", "title": "Engineering", "parent_id": None, "path": "", "source_id": "40", "taxonomy_id": 1},
                    ]
                }
            },
        }
    },
    tags=["V2 / Categories"],
)
def list_categories(db=Depends(get_db)):
    records = db.categories(limit=None)
    return JSONResponse(
        content=[formatter.format_category_record(r) for r in records]
    )


@router.get(
    "/account",
    summary="Get current account details",
    description="Returns the profile of the currently authenticated user.",
    responses={
        200: {"description": "Account details"},
        401: {"model": ErrorResponse, "description": "Invalid or missing session token"},
    },
    tags=["V2 / Account"],
)
def get_account(account=Depends(require_auth)):
    return JSONResponse(content=formatter.format_account_record(account))


# ---------------------------------------------------------------------------
# OAuth stubs — both endpoints exist as legacy stubs returning 404. Mirror
# that behaviour bit-for-bit so existing clients see no contract change.
# See djehuty.web.wsgi.api_authorize / api_token.
# ---------------------------------------------------------------------------

@router.api_route(
    "/account/applications/authorize",
    methods=["GET", "POST"],
    summary="OAuth authorize (stub)",
    description=(
        "Authorise an OAuth application. djehuty does not implement OAuth — "
        "this endpoint exists for Figshare-API parity and always returns 404."
    ),
    responses={404: {"model": ErrorResponse, "description": "Not implemented"}},
    tags=["V2 / Account"],
)
def oauth_authorize():
    raise NotFoundError()


@router.api_route(
    "/token",
    methods=["GET", "POST", "PUT", "DELETE"],
    summary="OAuth token (stub)",
    description=(
        "Issue an OAuth token. djehuty does not implement OAuth — "
        "this endpoint exists for Figshare-API parity and always returns 404."
    ),
    responses={404: {"model": ErrorResponse, "description": "Not implemented"}},
    tags=["V2 / Account"],
)
def oauth_token():
    raise NotFoundError()
