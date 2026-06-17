"""Authenticated dataset management endpoints for the v3 API."""

import hashlib
import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse

from djehuty.web import formatter
from djehuty.web.config import config
from djehuty.api.dependencies import get_db, get_current_account, require_auth
from djehuty.api.exceptions import NotFoundError, ForbiddenError, InvalidInputError

router = APIRouter(tags=["Dataset Management"])


def _resolve_any_dataset(db, dataset_id, account=None):
    """Resolve a dataset by ID/UUID, checking auth if available."""
    account_uuid = account["uuid"] if account else None
    try:
        try:
            numeric_id = int(dataset_id)
            return db.datasets(dataset_id=numeric_id, account_uuid=account_uuid, is_published=None, is_latest=None, limit=1)[0]
        except (ValueError, TypeError):
            return db.datasets(container_uuid=str(dataset_id), account_uuid=account_uuid, is_published=None, is_latest=None, limit=1)[0]
    except (IndexError, AttributeError):
        raise NotFoundError()


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
def list_references(dataset_id: str, db=Depends(get_db), account: dict | None = Depends(get_current_account)):
    dataset = _resolve_any_dataset(db, dataset_id, account)
    refs = db.references(item_uri=dataset["uri"])
    return JSONResponse(content=[formatter.format_reference_record(r) for r in refs])


@router.post("/datasets/{dataset_id}/references", summary="Add references", tags=["Dataset Metadata"])
def add_references(dataset_id: str, body: dict, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_dataset(db, dataset_id, account["uuid"])
    new_refs = body.get("references", [])
    existing = db.references(item_uri=dataset["uri"], account_uuid=account["uuid"])
    existing_urls = [r.get("url", "") for r in existing]
    combined = existing_urls + [r.get("url", r) if isinstance(r, dict) else r for r in new_refs if (r.get("url", r) if isinstance(r, dict) else r) not in existing_urls]
    db.update_item_list(dataset["uuid"], account["uuid"], combined, "references")
    return Response(status_code=205)


@router.delete("/datasets/{dataset_id}/references", summary="Delete a reference", tags=["Dataset Metadata"])
def delete_reference(dataset_id: str, url: str = Query(..., max_length=1024), account=Depends(require_auth), db=Depends(get_db)):
    from requests.utils import unquote
    dataset = _resolve_dataset(db, dataset_id, account["uuid"])
    decoded_url = unquote(url)
    existing = db.references(item_uri=dataset["uri"], account_uuid=account["uuid"])
    urls = [r.get("url", "") for r in existing]
    if decoded_url in urls:
        urls.remove(decoded_url)
        db.update_item_list(dataset["uuid"], account["uuid"], urls, "references")
    return Response(status_code=204)


@router.get("/datasets/{dataset_id}/tags", summary="List dataset tags", tags=["Dataset Metadata"])
def list_tags(dataset_id: str, db=Depends(get_db), account: dict | None = Depends(get_current_account)):
    dataset = _resolve_any_dataset(db, dataset_id, account)
    tags = db.tags(item_uri=dataset["uri"])
    return JSONResponse(content=[formatter.format_tag_record(t) for t in tags])


@router.post("/datasets/{dataset_id}/tags", summary="Add tags", tags=["Dataset Metadata"])
def add_tags(dataset_id: str, body: dict, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_dataset(db, dataset_id, account["uuid"])
    new_tags = body.get("tags", [])
    existing = db.tags(item_uri=dataset["uri"], account_uuid=account["uuid"])
    existing_values = [formatter.format_tag_record(t) for t in existing]
    combined = list(dict.fromkeys(existing_values + new_tags))  # deduplicate preserving order
    db.update_item_list(dataset["uuid"], account["uuid"], combined, "tags")
    return Response(status_code=205)


@router.delete("/datasets/{dataset_id}/tags", summary="Delete a tag", tags=["Dataset Metadata"])
def delete_tag(dataset_id: str, tag: str = Query(..., max_length=1024), account=Depends(require_auth), db=Depends(get_db)):
    from requests.utils import unquote
    dataset = _resolve_dataset(db, dataset_id, account["uuid"])
    decoded_tag = unquote(tag)
    existing = db.tags(item_uri=dataset["uri"], account_uuid=account["uuid"])
    tag_values = [formatter.format_tag_record(t) for t in existing]
    if decoded_tag in tag_values:
        tag_values.remove(decoded_tag)
        db.update_item_list(dataset["uuid"], account["uuid"], tag_values, "tags")
    return Response(status_code=204)


@router.get("/datasets/{dataset_id}/image-files", summary="List image files", tags=["Dataset Files"])
def list_image_files(dataset_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_dataset(db, dataset_id, account["uuid"])
    files = db.dataset_files(dataset_uri=dataset["uri"], account_uuid=account["uuid"])
    image_extensions = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".tif", ".tiff")
    image_files = [f for f in files if any(f.get("name", "").lower().endswith(ext) for ext in image_extensions)]
    return JSONResponse(content=[formatter.format_file_for_dataset_record(f) for f in image_files])


# ---------------------------------------------------------------------------
# Upload
#
# Native FastAPI port of /v3/datasets/<id>/upload. Same observable behaviour
# as the legacy ``api_v3_dataset_upload_file`` (status codes, response shape,
# storage path layout, MD5 strict-check semantics), but implemented using
# Starlette's built-in multipart parser (via ``UploadFile``) instead of the
# legacy's manual byte-level boundary parsing. Once api-service=new is the
# only configuration, the legacy 500-line implementation can be deleted.
# ---------------------------------------------------------------------------

_UPLOAD_CHUNK_SIZE = 4096
_EMPTY_FILE_MD5 = "d41d8cd98f00b204e9800998ecf8427e"


@router.post(
    "/datasets/{dataset_id}/upload",
    summary="Upload a file to a dataset",
    description=(
        "Stream-upload a single file into a draft dataset.\n\n"
        "Request body must be ``multipart/form-data`` with one file part.\n\n"
        "Query parameters:\n"
        "- ``strict_check=1`` — reject empty files, duplicate MD5s, and "
        "MD5 mismatches; the ``md5`` parameter becomes required.\n"
        "- ``md5`` — 32-character hex MD5 of the file's contents (required "
        "when ``strict_check=1``).\n\n"
        "Responses:\n"
        "- ``200`` — file accepted, ``{\"location\": \"<base>/v3/file/<uuid>\"}``\n"
        "- ``400`` — empty file, malformed body, or MD5 mismatch\n"
        "- ``403`` — account has no quota or no permission to edit dataset\n"
        "- ``409`` — duplicate file (only when ``strict_check=1``)\n"
        "- ``413`` — file exceeds remaining quota\n"
        "- ``415`` — not multipart/form-data"
    ),
    tags=["Dataset Files"],
)
async def upload_file(
    dataset_id: str,
    file: UploadFile = File(...),
    strict_check: int = Query(0, ge=0, le=1),
    md5: str | None = Query(None, min_length=32, max_length=32),
    account=Depends(require_auth),
    db=Depends(get_db),
):
    account_uuid = account["uuid"]

    # Quota check.
    account_record = db.account_by_uuid(account_uuid)
    if account_record is None or "quota" not in account_record:
        raise ForbiddenError(
            f"account:{account_uuid} attempted to upload a file but has no "
            f"assigned quota."
        )

    storage_used = db.account_storage_used(account_uuid)
    storage_available = account_record["quota"] - storage_used
    if storage_available < 1:
        raise HTTPException(status_code=413, detail="Quota exhausted.")

    # Dataset ownership check (must be the owner's draft).
    dataset = _resolve_dataset(db, dataset_id, account_uuid)

    # Strict-check pre-validation.
    if strict_check:
        if md5 is None:
            raise InvalidInputError(
                "md5 query parameter is required when strict_check=1.",
                "MissingMD5",
            )
        if md5 == _EMPTY_FILE_MD5:
            raise InvalidInputError("Empty file is not allowed.", "EmptyFile")
        for existing in db.dataset_files(
            dataset_uri=dataset["uri"], account_uuid=account_uuid
        ):
            if existing.get("computed_md5") == md5:
                raise HTTPException(
                    status_code=409,
                    detail="A file with the same MD5 is already attached.",
                )

    # Insert file metadata first so the file_uuid is available for the
    # destination filename. ``upload_url`` is stored verbatim for parity with
    # the legacy implementation.
    file_uuid = db.insert_file(
        name=file.filename or "untitled",
        size=0,
        is_link_only=0,
        upload_url=f"/article/{dataset_id}/upload",
        upload_token=None,
        dataset_uri=dataset["uri"],
        account_uuid=account_uuid,
    )

    output_filename = os.path.join(config.storage, f"{dataset_id}_{file_uuid}")
    md5_hasher = hashlib.new("md5", usedforsecurity=False)
    file_size = 0
    is_incomplete: int | None = None

    try:
        # Use os.open + write so we can chmod the same descriptor afterwards,
        # matching the legacy's permission-tightening behaviour.
        destination_fd = os.open(output_filename, os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                if file_size + len(chunk) > storage_available:
                    is_incomplete = 1
                    break
                written = os.write(destination_fd, chunk)
                file_size += written
                md5_hasher.update(chunk)
            if os.name != "nt":
                os.fchmod(destination_fd, 0o400)
        finally:
            os.close(destination_fd)
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail=f"Writing {output_filename} to disk failed: {error}",
        )

    computed_md5 = md5_hasher.hexdigest()

    # MD5 strict-check enforcement: clean up the partial upload then 400.
    if strict_check and computed_md5 != md5:
        try:
            from djehuty.utils.rdf import uuid_to_uri
            file_uri = uuid_to_uri(file_uuid, "file")
            if db.delete_item_from_list(dataset["uri"], "files", file_uri):
                db.cache.invalidate_by_prefix(f"{account_uuid}_storage")
                db.cache.invalidate_by_prefix(f"{dataset['uuid']}_dataset_storage")
        except (ImportError, KeyError, StopIteration):
            pass
        try:
            os.remove(output_filename)
        except OSError:
            pass
        raise InvalidInputError("MD5 checksum mismatch.", "MD5Mismatch")

    # Final metadata write. Handle registration is best-effort and only
    # relevant in production; we leave handle=None here.
    download_url = f"{config.base_url}/file/{dataset_id}/{file_uuid}"
    db.update_file(
        account_uuid, file_uuid, dataset["uuid"],
        computed_md5=computed_md5,
        download_url=download_url,
        filesystem_location=output_filename,
        file_size=file_size,
        is_image=False,
        is_incomplete=is_incomplete,
        handle=None,
    )

    response_data: dict[str, object] = {
        "location": f"{config.base_url}/v3/file/{file_uuid}"
    }
    if is_incomplete:
        response_data["is_incomplete"] = is_incomplete
    return JSONResponse(content=response_data)


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
    return Response(status_code=204)


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
