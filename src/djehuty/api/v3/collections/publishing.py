"""Collection author-order and publication endpoints for the v3 API."""

from fastapi import APIRouter, Body, Depends, Response
from fastapi.responses import JSONResponse

from djehuty.api.dependencies import get_db, require_auth
from djehuty.api.exceptions import ForbiddenError, InvalidInputError, NotFoundError
from djehuty.api.models.common import ErrorResponse
from djehuty.api.v3._shared import _ok
from djehuty.web.config import config

router = APIRouter(tags=["V3 / Collections"])


@router.post(
    "/collections/{container_uuid}/reorder-authors",
    summary="Reorder collection authors",
    responses={205: {"description": "Authors reordered"}, 403: {"model": ErrorResponse}},
)
def collection_reorder_authors(
    container_uuid: str,
    body: dict = Body(
        ...,
        openapi_examples={
            "move_up": {
                "summary": "Move an author up",
                "value": {"author": "07d6e6ce-b1bf-43ca-86e6-7a3ab8bc8416", "direction": "up"},
            }
        },
    ),
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
        account["uuid"],
        container_uuid,
        author_uuid,
        direction,
    ):
        raise InvalidInputError("Failed to reorder authors.", "ReorderFailed")
    return Response(status_code=205)


@router.post(
    "/collections/{collection_id}/publish",
    summary="Publish a draft collection",
    responses={
        201: _ok(
            "Collection published",
            {"location": "https://data.4tu.nl/published/6f9b2c1e-3a4d-5b6c-7d8e-9f0a1b2c3d4e"},
        ),
        403: {"model": ErrorResponse},
    },
)
def publish_collection(
    collection_id: str,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    from djehuty.web import validator

    # Resolve the collection by id (numeric or UUID).
    try:
        if validator.is_valid_uuid(collection_id):
            params = {"container_uuid": collection_id, "account_uuid": account["uuid"]}
        else:
            try:
                params = {"collection_id": int(collection_id), "account_uuid": account["uuid"]}
            except (ValueError, TypeError):
                raise ForbiddenError("Invalid collection id.")
        collection = db.collections(is_published=False, limit=1, **params)[0]
    except (IndexError, AttributeError):
        raise ForbiddenError("Collection not found or not owned.")

    errors: list = []
    validator.string_value(collection, "title", 3, 1000, True, errors)
    validator.string_value(collection, "description", 0, 10000, True, errors)
    validator.integer_value(collection, "group_id", 0, pow(2, 63), True, errors)
    validator.string_value(collection, "time_coverage", 0, 512, False, errors)
    validator.string_value(collection, "publisher", 0, 10000, True, errors)
    validator.string_value(collection, "language", 0, 10, True, errors)
    validator.string_value(collection, "resource_doi", 0, 255, False, errors)
    validator.string_value(collection, "resource_title", 0, 255, False, errors)

    authors = db.authors(item_uri=collection["uri"], item_type="collection")
    if not authors:
        errors.append(
            {
                "field_name": "authors",
                "message": "The collection must have at least one author.",
            }
        )
    tags = db.tags(item_uri=collection["uri"], account_uuid=account["uuid"])
    if not tags:
        errors.append(
            {
                "field_name": "tag",
                "message": "The collection must have at least one keyword.",
            }
        )
    categories = db.categories(
        item_uri=collection["uri"],
        account_uuid=account["uuid"],
        is_published=False,
        limit=None,
    )
    if not categories:
        errors.append(
            {
                "field_name": "categories",
                "message": "Please specify at least one category.",
            }
        )

    if errors:
        raise InvalidInputError(errors, "ValidationFailed")

    container_uuid = collection["container_uuid"]

    # DOI reservation is production-only and needs the DataCite helpers that
    # still live on the legacy server. Until they are extracted, production
    # deployments must keep the publish endpoint on the legacy stack.
    if config.in_production and not config.in_preproduction:
        raise InvalidInputError(
            "Publishing via the FastAPI implementation is not yet wired up "
            "for production DOI reservation.",
            "PublishUnavailableInProd",
        )

    if not db.publish_collection(container_uuid, account["uuid"]):
        raise InvalidInputError("Failed to publish collection.", "PublishFailed")

    return JSONResponse(
        content={"location": f"{config.base_url}/published/{collection_id}"},
        status_code=201,
    )
