"""OAuth stubs. djehuty does not implement OAuth; these exist for Figshare-API
parity and always return 404, exactly as the legacy handlers do."""

from fastapi import APIRouter

from djehuty.api.exceptions import NotFoundError
from djehuty.api.models.common import ErrorResponse

router = APIRouter(tags=["V2 / Account"])


@router.api_route(
    "/account/applications/authorize",
    methods=["GET", "POST"],
    summary="OAuth authorize (stub)",
    description="Not implemented; always returns 404.",
    responses={404: {"model": ErrorResponse, "description": "Not implemented"}},
)
def oauth_authorize():
    raise NotFoundError()


@router.api_route(
    "/token",
    methods=["GET", "POST", "PUT", "DELETE"],
    summary="OAuth token (stub)",
    description="Not implemented; always returns 404.",
    responses={404: {"model": ErrorResponse, "description": "Not implemented"}},
)
def oauth_token():
    raise NotFoundError()
