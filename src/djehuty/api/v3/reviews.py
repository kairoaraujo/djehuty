"""Review endpoints for the v3 API."""

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from djehuty.api.dependencies import get_db, require_auth
from djehuty.api.exceptions import ForbiddenError, InvalidInputError
from djehuty.api.models.common import ErrorResponse
from djehuty.api.v3._shared import _ok
from djehuty.web import formatter

router = APIRouter(tags=["V3 / Reviews"])

_REVIEW_EXAMPLE = {
    "uuid": "669c6802-75eb-44e2-a6f8-ea7a5a8d0f34",
    "container_uuid": "b07402ed-978b-439a-abb1-7f27c69d174e",
    "dataset_title": "Coastal water temperature measurements",
    "dataset_uuid": "8ffc3b0f-ec65-4dab-bae1-49ff984c2995",
    "dataset_version": 1,
    "group_name": "Delft University of Technology",
    "has_published_version": 1,
    "last_seen_by_reviewer": None,
    "modified_date": "2026-07-03T09:33:38",
    "published_date": "2026-07-03T09:33:40",
    "request_date": "2026-07-03T09:33:38",
    "reviewer_email": "dev@djehuty.com",
    "reviewer_first_name": "Ada",
    "reviewer_last_name": "Lovelace",
    "status": "approved",
    "submitter_email": "dev@djehuty.com",
    "submitter_first_name": "Ada",
    "submitter_last_name": "Lovelace",
}

_REVIEWER_EXAMPLE = {
    "id": None,
    "uuid": "84cae99f-a691-4af2-9d21-f5c0817c26df",
    "first_name": "Dev",
    "last_name": "User",
    "full_name": None,
    "is_active": True,
    "is_public": False,
    "job_title": None,
    "orcid_id": "",
}


@router.get(
    "/reviews",
    summary="List reviews",
    responses={200: _ok("Review records", [_REVIEW_EXAMPLE]), 403: {"model": ErrorResponse}},
)
def list_reviews(account=Depends(require_auth), db=Depends(get_db)):
    reviews = db.reviews(account_uuid=account["uuid"])
    return JSONResponse(content=[formatter.format_review_record(r) for r in reviews])


@router.get(
    "/reviewers",
    summary="List reviewers",
    responses={200: _ok("Reviewer accounts", [_REVIEWER_EXAMPLE]), 403: {"model": ErrorResponse}},
)
def list_reviewers(account=Depends(require_auth), db=Depends(get_db)):
    reviewers = db.reviewer_accounts()
    return JSONResponse(content=[formatter.format_account_record(r) for r in reviewers])


@router.put(
    "/datasets/{container_uuid}/assign-reviewer/{reviewer_uuid}",
    summary="Assign reviewer",
    responses={204: {"description": "Reviewer assigned"}, 403: {"model": ErrorResponse}},
)
def assign_reviewer(
    container_uuid: str,
    reviewer_uuid: str,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    from djehuty.web import validator

    if not validator.is_valid_uuid(reviewer_uuid):
        raise ForbiddenError("Invalid reviewer UUID.")

    if not (db.may_review(account.get("uuid")) or db.may_review_institution(account.get("uuid"))):
        raise ForbiddenError("Reviewer permissions required.")

    reviewer = db.account_by_uuid(reviewer_uuid)
    try:
        dataset = db.datasets(
            container_uuid=container_uuid,
            is_published=False,
            is_under_review=True,
            limit=1,
        )[0]
    except (IndexError, AttributeError, TypeError):
        raise ForbiddenError("Dataset not found or not under review.")

    if reviewer is None:
        raise ForbiddenError("Reviewer not found.")

    if not db.update_review(
        dataset["review_uri"],
        author_account_uuid=dataset["account_uuid"],
        assigned_to=reviewer["uuid"],
        status="assigned",
    ):
        raise InvalidInputError("Failed to assign reviewer.", "AssignFailed")
    return Response(status_code=204)
