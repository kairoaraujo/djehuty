"""Authenticated /v2/account/articles articles endpoints."""

from fastapi import APIRouter, Body, Depends, Response
from fastapi.responses import JSONResponse

from djehuty.api.dependencies import get_db, get_token, pagination_params, require_auth
from djehuty.api.exceptions import ForbiddenError, InvalidInputError, NotFoundError
from djehuty.api.models.common import ErrorResponse
from djehuty.api.services.article_service import ArticleService
from djehuty.api.v2.account.articles._shared import _ok, _resolve_private_dataset
from djehuty.web import formatter
from djehuty.web.config import config

router = APIRouter(prefix="/account", tags=["V2 / Account / Articles"])


def _get_service(db=Depends(get_db)) -> ArticleService:
    return ArticleService(db)


_LOCATION_EXAMPLE = {
    "location": "https://data.4tu.nl/v2/account/articles/d7b3daa5-45e2-47b0-9910-0f7fa6a995b1",
    "warnings": [],
}


@router.get(
    "/articles",
    summary="List own draft articles",
    description="Returns the authenticated user's draft (unpublished) articles.",
    responses={
        200: {"description": "List of draft articles"},
        403: {"model": ErrorResponse},
    },
)
def list_private_articles(
    account=Depends(require_auth),
    db=Depends(get_db),
    paging: dict = Depends(pagination_params),
):
    records = db.datasets(
        limit=paging["limit"],
        offset=paging["offset"],
        is_published=False,
        account_uuid=account["uuid"],
    )
    return JSONResponse(
        content=[
            formatter.format_dataset_record({**r, "base_url": config.base_url}) for r in records
        ]
    )


@router.post(
    "/articles",
    status_code=200,
    summary="Create a new article",
    description=(
        "Create a new draft article (dataset). Returns the location URL "
        "of the newly created article."
    ),
    responses={
        200: _ok("Article created", _LOCATION_EXAMPLE),
        400: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
def create_article(
    body: dict = Body(
        ...,
        openapi_examples={
            "minimal": {"summary": "Title only", "value": {"title": "Example dataset"}},
            "with_metadata": {
                "summary": "Title and description",
                "value": {"title": "Example dataset", "description": "A short description."},
            },
        },
    ),
    account=Depends(require_auth),
    db=Depends(get_db),
    token: str | None = Depends(get_token),
):
    from djehuty.utils.convenience import value_or_none
    from djehuty.web import validator

    account_uuid = account["uuid"]

    if not db.is_depositor(token, account):
        raise ForbiddenError("Account is not allowed to deposit.")

    try:
        license_id = validator.integer_value(body, "license", 0, pow(2, 63), False)
        license_url = db.license_url_by_id(license_id)
        timeline = validator.object_value(body, "timeline", False)

        group_id = validator.integer_value(body, "group_id", 0, pow(2, 63), False)
        if group_id is None:
            acct = db.account_by_uuid(account_uuid)
            group_id = value_or_none(acct, "group_id")

        publisher = validator.string_value(body, "publisher", 0, 255, False)
        if publisher is None:
            publisher = config.site_name

        container_uuid, _ = db.insert_dataset(
            title=validator.string_value(body, "title", 3, 1000, True),
            account_uuid=account_uuid,
            description=validator.string_value(
                body, "description", 0, 10000, False, strip_html=False
            ),
            defined_type_name=validator.options_value(
                body, "defined_type", validator.dataset_types, False
            ),
            funding=validator.string_value(body, "funding", 0, 255, False),
            license_url=license_url,
            language=validator.string_value(body, "language", 0, 8, False),
            doi=validator.string_value(body, "doi", 0, 255, False),
            handle=validator.string_value(body, "handle", 0, 255, False),
            resource_doi=validator.string_value(body, "resource_doi", 0, 255, False),
            resource_title=validator.string_value(body, "resource_title", 0, 255, False),
            group_id=group_id,
            publisher=publisher,
            custom_fields=validator.object_value(body, "custom_fields", False),
            custom_fields_list=validator.array_value(body, "custom_fields_list", False),
            publisher_publication=validator.string_value(timeline, "publisherPublication", False)
            if timeline
            else None,
            submission=validator.string_value(timeline, "submission", False) if timeline else None,
            posted=validator.string_value(timeline, "posted", False) if timeline else None,
            revision=validator.string_value(timeline, "revision", False) if timeline else None,
        )

        return JSONResponse(
            content={
                "location": f"{config.base_url}/v2/account/articles/{container_uuid}",
                "warnings": [],
            }
        )
    except validator.ValidationException as error:
        raise InvalidInputError(error.message, error.code)


@router.post(
    "/articles/search",
    summary="Search own articles",
    responses={200: {"description": "Search results"}, 403: {"model": ErrorResponse}},
)
def search_private_articles(
    body: dict,
    account=Depends(require_auth),
    service: ArticleService = Depends(_get_service),
):
    from djehuty.utils.convenience import value_or_none

    search_for = value_or_none(body, "search_for")
    limit = body.get("limit", 10)
    offset = body.get("offset", 0)

    records = service.list_articles(
        limit=limit,
        offset=offset,
        search_for=search_for,
        is_published=False,
        account_uuid=account["uuid"],
    )
    return JSONResponse(content=records)


@router.get(
    "/articles/{dataset_id}",
    summary="Get own article details",
    responses={
        200: {"description": "Article details"},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def get_private_article(
    dataset_id: str,
    account=Depends(require_auth),
    service: ArticleService = Depends(_get_service),
):
    result = service.get_article_details(
        dataset_id, account_uuid=account["uuid"], is_published=False
    )
    if result is None:
        # Legacy returns 200 with empty array when dataset not found
        return JSONResponse(content=[])
    return JSONResponse(content=result)


@router.put(
    "/articles/{dataset_id}",
    summary="Update an article",
    responses={
        200: {"description": "Article updated"},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def update_article(
    dataset_id: str,
    body: dict,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    from djehuty.web import validator

    account_uuid = account["uuid"]
    dataset = _resolve_private_dataset(db, dataset_id, account_uuid)

    try:
        license_id = validator.integer_value(body, "license_id", 0, pow(2, 63))
        license_url = db.license_url_by_id(license_id) if license_id else None

        is_embargoed = (
            "embargo_date" in body
            or validator.string_value(body, "embargo_type", 0, 255) is not None
        )
        embargo_options = validator.array_value(body, "embargo_options")
        is_restricted = False
        is_closed = False
        if embargo_options:
            from djehuty.utils.convenience import value_or

            embargo_option = embargo_options[0] if embargo_options else None
            is_restricted = value_or(embargo_option, "id", 0) == 1000
            is_closed = value_or(embargo_option, "id", 0) == 1001
        is_temporary_embargo = is_embargoed and not is_restricted and not is_closed

        result = db.update_dataset(
            dataset["uuid"],
            account_uuid,
            title=validator.string_value(body, "title", 3, 1000),
            description=validator.string_value(body, "description", 0, 10000, strip_html=False),
            resource_doi=validator.string_value(body, "resource_doi", 0, 255),
            resource_title=validator.string_value(body, "resource_title", 0, 255),
            license_url=license_url,
            group_id=validator.integer_value(body, "group_id", 0, pow(2, 63)),
            time_coverage=validator.string_value(body, "time_coverage", 0, 512),
            publisher=validator.string_value(body, "publisher", 0, 10000),
            language=validator.string_value(body, "language", 0, 8),
            contributors=validator.string_value(body, "contributors", 0, 10000),
            license_remarks=validator.string_value(body, "license_remarks", 0, 10000),
            geolocation=validator.string_value(body, "geolocation", 0, 255),
            longitude=validator.string_value(body, "longitude", 0, 64),
            latitude=validator.string_value(body, "latitude", 0, 64),
            mimetype=validator.string_value(body, "format", 0, 512),
            data_link=validator.string_value(body, "data_link", 0, 255),
            derived_from=validator.string_value(body, "derived_from", 0, 255),
            same_as=validator.string_value(body, "same_as", 0, 255),
            organizations=validator.string_value(body, "organizations", 0, 2048),
            is_embargoed=is_embargoed,
            is_restricted=is_restricted,
            is_metadata_record=validator.boolean_value(body, "is_metadata_record", when_none=False),
            metadata_reason=validator.string_value(
                body, "metadata_reason", 0, 512, strip_html=False
            ),
            embargo_until_date=validator.date_value(
                body, "embargo_until_date", is_temporary_embargo
            ),
            embargo_type=validator.options_value(body, "embargo_type", validator.embargo_types),
            embargo_title=validator.string_value(body, "embargo_title", 0, 1000),
            embargo_reason=validator.string_value(
                body, "embargo_reason", 0, 10000, strip_html=False
            ),
            eula=validator.string_value(body, "eula", 0, 50000, strip_html=False),
        )

        if not result:
            raise NotFoundError()

        return Response(status_code=205)
    except validator.ValidationException as error:
        raise InvalidInputError(error.message, error.code)


@router.delete(
    "/articles/{dataset_id}",
    summary="Delete a draft article",
    responses={
        204: {"description": "Article deleted"},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
    },
)
def delete_article(
    dataset_id: str,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    try:
        dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
        if db.delete_dataset_draft(
            dataset["container_uuid"], dataset["uuid"], account["uuid"], dataset["account_uuid"]
        ):
            return Response(status_code=204)
    except NotFoundError:
        pass
    # Legacy returns 500 for both not-found and failed deletes.
    # Documented in doc/api-improvements.md for future correction.
    return JSONResponse(status_code=500, content="")
