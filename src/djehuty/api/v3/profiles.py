"""Profile endpoints for the v3 API."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from djehuty.web import formatter
from djehuty.api.dependencies import get_db, require_auth
from djehuty.api.exceptions import NotFoundError

router = APIRouter(tags=["Profiles"])


@router.get("/profile", summary="Get current user profile")
def get_profile(account=Depends(require_auth), db=Depends(get_db)):
    return JSONResponse(content=formatter.format_account_details_record(account))


@router.get("/profile/categories", summary="Get profile categories")
def get_profile_categories(account=Depends(require_auth), db=Depends(get_db)):
    categories = db.account_categories(account["uuid"])
    return JSONResponse(content=[formatter.format_category_record(c) for c in categories])


@router.get("/profile/quota-request", summary="Get quota request status")
def get_quota_request(account=Depends(require_auth), db=Depends(get_db)):
    requests = db.quota_requests(account_uuid=account["uuid"])
    return JSONResponse(content=requests)


@router.get("/profile/picture/{account_uuid}", summary="Get profile picture for an account")
def get_profile_picture_for_account(account_uuid: str, db=Depends(get_db)):
    from djehuty.web import validator
    if not validator.is_valid_uuid(account_uuid):
        raise NotFoundError()

    try:
        acct = db.account_by_uuid(account_uuid)
        file_path = acct["profile_image"]
        # File serving is handled by the legacy app for now
        raise NotFoundError()
    except (KeyError, FileNotFoundError):
        raise NotFoundError()
