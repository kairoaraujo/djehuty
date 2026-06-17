"""Profile endpoints for the v3 API."""

import os

from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse, JSONResponse

from djehuty.web import formatter
from djehuty.web.config import config
from djehuty.api.dependencies import get_db, require_auth
from djehuty.api.exceptions import InvalidInputError, NotFoundError, ForbiddenError

router = APIRouter(tags=["Profiles"])


@router.get("/profile", summary="Get current user profile")
def get_profile(account=Depends(require_auth), db=Depends(get_db)):
    return JSONResponse(content=formatter.format_account_details_record(account))


@router.put("/profile", summary="Update current user profile")
def update_profile(
    body: dict, account=Depends(require_auth), db=Depends(get_db),
):
    from djehuty.web import validator

    if not isinstance(body, dict):
        raise InvalidInputError("Request body must be a JSON object.", "BadBody")

    try:
        categories = validator.array_value(body, "categories")
        if categories is not None:
            for index, _ in enumerate(categories):
                categories[index] = validator.string_value(categories, index, 36, 36)

        if db.update_account(
            account["uuid"],
            active=validator.integer_value(body, "active", 0, 1),
            job_title=validator.string_value(body, "job_title", 0, 255),
            email=validator.string_value(body, "email", 0, 255),
            first_name=validator.string_value(body, "first_name", 0, 255),
            last_name=validator.string_value(body, "last_name", 0, 255),
            location=validator.string_value(body, "location", 0, 255),
            twitter=validator.string_value(body, "twitter", 0, 255),
            linkedin=validator.string_value(body, "linkedin", 0, 255),
            website=validator.string_value(body, "website", 0, 255),
            biography=validator.string_value(body, "biography", 0, 32768),
            institution_user_id=validator.integer_value(body, "institution_user_id"),
            institution_id=validator.integer_value(body, "institution_id"),
            maximum_file_size=validator.integer_value(body, "maximum_file_size"),
            modified_date=validator.string_value(body, "modified_date", 0, 32),
            categories=categories,
        ):
            return Response(status_code=204)
        raise InvalidInputError("Failed to update account.", "UpdateFailed")
    except validator.ValidationException as error:
        raise InvalidInputError(error.message, error.code)


@router.get("/profile/categories", summary="Get profile categories")
def get_profile_categories(account=Depends(require_auth), db=Depends(get_db)):
    categories = db.account_categories(account["uuid"])
    return JSONResponse(content=[formatter.format_category_record(c) for c in categories])


@router.post("/profile/quota-request", summary="Submit a quota request")
def submit_quota_request(
    body: dict, account=Depends(require_auth), db=Depends(get_db),
):
    from djehuty.services import email as email_module
    from djehuty.web import validator

    try:
        quota_gb = validator.integer_value(body, "new-quota", required=True)
        reason = validator.string_value(
            body, "reason", 0, 10000, required=True, strip_html=False
        )

        if quota_gb < 1:
            raise InvalidInputError(
                "Requested quota must be at least 1 gigabyte.",
                "QuotaRequestSizeTooSmall",
            )

        new_quota = quota_gb * 1_000_000_000
        quota_uuid = db.insert_quota_request(account["uuid"], new_quota, reason)
        if quota_uuid is None:
            raise InvalidInputError(
                "Failed to register quota request.", "QuotaRequestFailed"
            )

        account_record = db.account_by_uuid(account["uuid"])
        email_module.send_email_to_quota_reviewers(
            db,
            f"Quota request for {account['uuid']}",
            "quota_request",
            email=account_record.get("email") if account_record else None,
            new_quota=quota_gb,
            reason=reason,
        )

        return Response(status_code=204)
    except validator.ValidationException as error:
        raise InvalidInputError(error.message, error.code)


@router.get("/profile/picture", summary="Get own profile picture")
def get_own_profile_picture(account=Depends(require_auth), db=Depends(get_db)):
    from djehuty.services.imaging import image_mimetype

    file_path = account.get("profile_image")
    if not file_path or not os.path.isfile(file_path):
        raise NotFoundError()

    mimetype = image_mimetype(file_path)
    if mimetype is None:
        raise ForbiddenError("Unsupported image format.")

    return FileResponse(file_path, media_type=mimetype)


@router.get("/profile/picture/{account_uuid}", summary="Get profile picture for an account")
def get_profile_picture_for_account(account_uuid: str, db=Depends(get_db)):
    from djehuty.services.imaging import image_mimetype
    from djehuty.web import validator

    if not validator.is_valid_uuid(account_uuid):
        raise NotFoundError()

    try:
        acct = db.account_by_uuid(account_uuid)
        file_path = acct["profile_image"]
        if not os.path.isfile(file_path):
            raise NotFoundError()

        mimetype = image_mimetype(file_path)
        if mimetype is None:
            raise ForbiddenError("Unsupported image format.")
        return FileResponse(file_path, media_type=mimetype)
    except (KeyError, TypeError, FileNotFoundError):
        raise NotFoundError()
