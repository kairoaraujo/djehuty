"""Authenticated dataset management endpoints for the v3 API."""

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse

from djehuty.web import formatter
from djehuty.web.config import config
from djehuty.api.dependencies import get_db, require_auth
from djehuty.api.exceptions import NotFoundError, ForbiddenError, InvalidInputError

router = APIRouter(tags=["Dataset Management"])


def _resolve_dataset(db, dataset_id, account_uuid):
    """Resolve a dataset by ID/UUID with ownership check."""
    try:
        try:
            numeric_id = int(dataset_id)
            return db.datasets(dataset_id=numeric_id, account_uuid=account_uuid, is_published=False)[0]
        except (ValueError, TypeError):
            return db.datasets(container_uuid=str(dataset_id), account_uuid=account_uuid, is_published=False)[0]
    except (IndexError, AttributeError):
        raise NotFoundError()


@router.post(
    "/datasets/{dataset_id}/submit-for-review",
    summary="Submit dataset for review",
    description="Submit a draft dataset for curator review before publication.",
)
def submit_for_review(dataset_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_dataset(db, dataset_id, account["uuid"])
    result = db.submit_dataset_for_review(dataset["uri"], account["uuid"])
    if not result:
        raise InvalidInputError("Failed to submit for review.", "SubmitFailed")
    return Response(status_code=204)


@router.post(
    "/datasets/{dataset_id}/publish",
    summary="Publish a dataset",
    description=(
        "Publish a draft dataset. Requires reviewer permissions on the "
        "calling account. The production DataCite DOI reservation flow is "
        "gated by ``config.in_production`` and skipped in dev/preproduction."
    ),
)
def publish_dataset(
    dataset_id: str, account=Depends(require_auth), db=Depends(get_db)
):
    if not (db.may_review(account.get("uuid"))
            or db.may_review_institution(account.get("uuid"))):
        raise ForbiddenError("Reviewer permissions required.")

    dataset = _resolve_dataset(db, dataset_id, account["uuid"])

    if db.may_review_institution(account.get("uuid")):
        if account.get("group_id") != dataset.get("group_id"):
            raise ForbiddenError("Reviewer group mismatch.")

    review_uri = dataset.get("review_uri")
    if review_uri:
        db.update_review(
            review_uri,
            author_account_uuid=dataset["account_uuid"],
            assigned_to=account.get("uuid"),
            status="assigned",
        )

    if config.in_production and not config.in_preproduction:
        # TODO: DataCite DOI helpers live on the legacy server; production
        # deployments must keep ``api-service = legacy`` until they are
        # extracted into a shared module.
        raise InvalidInputError(
            "Publishing via the FastAPI implementation is not yet wired up "
            "for production DOI reservation.",
            "PublishUnavailableInProd",
        )

    if not db.publish_dataset(dataset["container_uuid"], account["uuid"]):
        raise InvalidInputError("Failed to publish dataset.", "PublishFailed")

    return JSONResponse(
        content={"location": f"{config.base_url}/published/{dataset_id}"},
        status_code=201,
    )


@router.post(
    "/datasets/{dataset_id}/decline",
    summary="Decline a dataset (reviewer)",
    description="Decline a dataset that was submitted for review. Requires reviewer privileges.",
)
def decline_dataset(
    dataset_id: str, account=Depends(require_auth), db=Depends(get_db)
):
    if not (db.may_review(account.get("uuid"))
            or db.may_review_institution(account.get("uuid"))):
        raise ForbiddenError("Reviewer permissions required.")

    dataset = _resolve_dataset(db, dataset_id, account["uuid"])

    if db.may_review_institution(account.get("uuid")):
        if account.get("group_id") != dataset.get("group_id"):
            raise ForbiddenError("Reviewer group mismatch.")

    if not db.decline_dataset(dataset["container_uuid"], account["uuid"]):
        raise InvalidInputError("Failed to decline dataset.", "DeclineFailed")

    return JSONResponse(
        content={"location": f"{config.base_url}/review/overview"},
        status_code=201,
    )


@router.get("/datasets/{dataset_id}/references", summary="List dataset references", tags=["Dataset Metadata"])
def list_references(dataset_id: str, db=Depends(get_db)):
    try:
        dataset = db.datasets(container_uuid=str(dataset_id), is_latest=True)[0]
    except (IndexError, AttributeError):
        raise NotFoundError()
    refs = db.references(item_uri=dataset["uri"])
    return JSONResponse(content=[formatter.format_reference_record(r) for r in refs])


@router.get("/datasets/{dataset_id}/tags", summary="List dataset tags", tags=["Dataset Metadata"])
def list_tags(dataset_id: str, db=Depends(get_db)):
    try:
        dataset = db.datasets(container_uuid=str(dataset_id), is_latest=True)[0]
    except (IndexError, AttributeError):
        raise NotFoundError()
    tags = db.tags(item_uri=dataset["uri"])
    return JSONResponse(content=[formatter.format_tag_record(t) for t in tags])


@router.get("/datasets/{dataset_id}/image-files", summary="List image files", tags=["Dataset Files"])
def list_image_files(dataset_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_dataset(db, dataset_id, account["uuid"])
    files = db.dataset_files(dataset_uri=dataset["uri"], account_uuid=account["uuid"])
    image_extensions = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".tif", ".tiff")
    image_files = [f for f in files if any(f.get("name", "").lower().endswith(ext) for ext in image_extensions)]
    return JSONResponse(content=[formatter.format_file_for_dataset_record(f) for f in image_files])


# --- Collaborators ---

@router.get("/datasets/{container_uuid}/collaborators", summary="List collaborators", tags=["Collaborators"])
def list_collaborators(container_uuid: str, account=Depends(require_auth), db=Depends(get_db)):
    collaborators = db.collaborators(container_uuid=container_uuid, account_uuid=account["uuid"])
    return JSONResponse(content=[formatter.format_collaborator_record(c) for c in collaborators])


@router.put("/datasets/{container_uuid}/collaborators/{collaborator_uuid}", summary="Add/update collaborator", tags=["Collaborators"])
def update_collaborator(
    container_uuid: str,
    collaborator_uuid: str,
    body: dict,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    if not isinstance(body, dict):
        raise InvalidInputError("Request body must be a JSON object.", "BadBody")
    if not db.update_collaborator(
        container_uuid=container_uuid,
        collaborator_uuid=collaborator_uuid,
        account_uuid=account["uuid"],
        permissions=body,
    ):
        raise InvalidInputError("Failed to update collaborator.", "UpdateFailed")
    return Response(status_code=204)


@router.delete("/datasets/{container_uuid}/collaborators/{collaborator_uuid}", summary="Remove collaborator", tags=["Collaborators"])
def delete_collaborator(container_uuid: str, collaborator_uuid: str, account=Depends(require_auth), db=Depends(get_db)):
    db.delete_collaborator(container_uuid=container_uuid, collaborator_uuid=collaborator_uuid)
    return JSONResponse(status_code=204, content=None)


# --- Authors (v3 format) ---

@router.get("/datasets/{container_uuid}/authors", summary="List dataset authors (v3)", tags=["Dataset Authors"])
def list_dataset_authors_v3(container_uuid: str, db=Depends(get_db)):
    try:
        dataset = db.datasets(container_uuid=container_uuid, is_latest=None)[0]
    except (IndexError, AttributeError):
        raise NotFoundError()
    authors = db.authors(item_uri=dataset["uri"], item_type="dataset", limit=10000)
    return JSONResponse(content=[formatter.format_author_record_v3(a) for a in authors])


@router.post("/datasets/{container_uuid}/reorder-authors", summary="Reorder authors", tags=["Dataset Authors"])
def reorder_authors(
    container_uuid: str,
    body: dict,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    from djehuty.web import validator

    if not validator.is_valid_uuid(container_uuid):
        raise NotFoundError()
    if not isinstance(body, dict):
        raise InvalidInputError("Request body must be a JSON object.", "BadBody")

    direction = body.get("direction")
    if direction not in ("up", "down"):
        raise InvalidInputError("direction must be 'up' or 'down'.", "BadDirection")
    author_uuid = body.get("author")
    if not author_uuid or not validator.is_valid_uuid(author_uuid):
        raise InvalidInputError("author must be a valid UUID.", "BadAuthor")

    if not db.reorder_authors(
        account["uuid"], container_uuid, author_uuid, direction
    ):
        raise InvalidInputError("Failed to reorder authors.", "ReorderFailed")
    return Response(status_code=205)


# --- Reviews ---

@router.get("/reviews", summary="List reviews", tags=["Reviews"])
def list_reviews(account=Depends(require_auth), db=Depends(get_db)):
    reviews = db.reviews(account_uuid=account["uuid"])
    return JSONResponse(content=[formatter.format_review_record(r) for r in reviews])


@router.get("/reviewers", summary="List reviewers", tags=["Reviews"])
def list_reviewers(account=Depends(require_auth), db=Depends(get_db)):
    reviewers = db.reviewers()
    return JSONResponse(content=[formatter.format_account_record(r) for r in reviewers])


@router.put(
    "/datasets/{container_uuid}/assign-reviewer/{reviewer_uuid}",
    summary="Assign reviewer",
    tags=["Reviews"],
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

    if not (db.may_review(account.get("uuid"))
            or db.may_review_institution(account.get("uuid"))):
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


# --- Statistics ---

@router.get("/datasets/top/{item_type}", summary="Get top datasets by type", tags=["Statistics"])
def datasets_top(item_type: str, db=Depends(get_db), limit: int = Query(10, ge=1, le=100)):
    records = db.dataset_statistics(item_type=item_type, limit=limit)
    return JSONResponse(content=records)


@router.get("/datasets/timeline/{item_type}", summary="Get dataset timeline", tags=["Statistics"])
def datasets_timeline(item_type: str, db=Depends(get_db)):
    records = db.dataset_statistics_timeline(item_type=item_type)
    return JSONResponse(content=records)


# --- Collections (v3) ---

@router.get("/collections/{collection_id}/references", summary="List collection references", tags=["Collection Metadata"])
def list_collection_references(collection_id: str, db=Depends(get_db)):
    try:
        collection = db.collections(container_uuid=str(collection_id), is_latest=True)[0]
    except (IndexError, AttributeError):
        raise NotFoundError()
    refs = db.references(item_uri=collection["uri"])
    return JSONResponse(content=[formatter.format_reference_record(r) for r in refs])


@router.get("/collections/{collection_id}/tags", summary="List collection tags", tags=["Collection Metadata"])
def list_collection_tags(collection_id: str, db=Depends(get_db)):
    try:
        collection = db.collections(container_uuid=str(collection_id), is_latest=True)[0]
    except (IndexError, AttributeError):
        raise NotFoundError()
    tags = db.tags(item_uri=collection["uri"])
    return JSONResponse(content=[formatter.format_tag_record(t) for t in tags])


# --- Explorer ---

@router.get("/explore/types", summary="List data model types", tags=["Explorer"])
def explore_types(db=Depends(get_db)):
    records = db.explorer_types()
    return JSONResponse(content=records)


@router.get("/explore/properties", summary="List data model properties", tags=["Explorer"])
def explore_properties(db=Depends(get_db)):
    records = db.explorer_properties()
    return JSONResponse(content=records)


@router.get("/explore/property_value_types", summary="List property value types", tags=["Explorer"])
def explore_property_value_types(db=Depends(get_db)):
    records = db.explorer_property_types()
    return JSONResponse(content=records)


@router.get("/explore/clear-cache", summary="Clear explorer cache", tags=["Explorer"])
def explore_clear_cache(account=Depends(require_auth), db=Depends(get_db)):
    # Legacy gates this behind ``may_administer``; mirror that.
    if not db.may_administer(account.get("uuid")):
        raise ForbiddenError("Administrator permissions required.")
    db.cache.invalidate_all()
    return Response(status_code=204)


# --- Admin ---

@router.get("/admin/files-integrity-statistics", summary="File integrity statistics", tags=["Admin"])
def files_integrity_statistics(account=Depends(require_auth), db=Depends(get_db)):
    records = db.files_integrity_statistics()
    return JSONResponse(content=records)


@router.get("/admin/accounts/clear-cache", summary="Clear accounts cache", tags=["Admin"])
def admin_clear_accounts_cache(account=Depends(require_auth), db=Depends(get_db)):
    if not db.may_administer(account.get("uuid")):
        raise ForbiddenError("Administrator permissions required.")
    db.cache.invalidate_by_prefix("accounts")
    return Response(status_code=204)


@router.get("/admin/reviews/clear-cache", summary="Clear reviews cache", tags=["Admin"])
def admin_clear_reviews_cache(account=Depends(require_auth), db=Depends(get_db)):
    if not db.may_administer(account.get("uuid")):
        raise ForbiddenError("Administrator permissions required.")
    db.cache.invalidate_by_prefix("reviews")
    return Response(status_code=204)


# --- SSI ---

@router.put("/receive-from-ssi", summary="Receive dataset from SSI", tags=["SSI"])
def receive_from_ssi(body: dict, db=Depends(get_db)):
    import hmac
    from djehuty.web import validator

    if config.ssi_psk is None:
        raise NotFoundError()

    psk = body.get("psk", "")
    if not hmac.compare_digest(str(psk), config.ssi_psk):
        raise ForbiddenError()

    title = validator.string_value(body, "title", 0, 255, True)
    email = validator.string_value(body, "email", 0, 255, True)

    acct = db.account_by_email(email)
    account_uuid = acct["uuid"] if acct else db.insert_account(email=email)

    token, _, session_uuid = db.insert_session(account_uuid, name="Login via SSI")
    container_uuid, _ = db.insert_dataset(title=title, account_uuid=account_uuid)

    from fastapi.responses import RedirectResponse
    return RedirectResponse(
        url=f"{config.base_url}/v3/redirect-from-ssi/{container_uuid}/{token}",
        status_code=302,
    )


@router.get("/redirect-from-ssi/{container_uuid}/{token}", summary="Complete SSI redirect", tags=["SSI"])
def redirect_from_ssi(container_uuid: str, token: str):
    from djehuty.web import validator
    if not validator.is_valid_uuid(container_uuid):
        raise ForbiddenError()

    from fastapi.responses import RedirectResponse
    response = RedirectResponse(url=f"/my/datasets/{container_uuid}/edit", status_code=302)
    response.set_cookie(
        key="djehuty_session", value=token,
        secure=config.in_production, httponly=True, samesite="lax",
    )
    return response
