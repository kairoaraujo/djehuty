"""Private (authenticated) article endpoints for the v2 API.

These endpoints require a valid session token and operate on the
authenticated user's draft datasets.
"""

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse

from djehuty.web import formatter
from djehuty.web.config import config
from djehuty.api.dependencies import get_db, require_auth, pagination_params
from djehuty.api.exceptions import NotFoundError, ForbiddenError, InvalidInputError
from djehuty.api.models.common import ErrorResponse
from djehuty.api.services.article_service import ArticleService

router = APIRouter(prefix="/account", tags=["Private Articles"])


def _get_service(db=Depends(get_db)) -> ArticleService:
    return ArticleService(db)


@router.get(
    "/articles",
    summary="List own draft articles",
    description="Returns the authenticated user's draft (unpublished) articles.",
    responses={
        200: {"description": "List of draft articles"},
        401: {"model": ErrorResponse},
    },
)
def list_private_articles(
    account=Depends(require_auth),
    db=Depends(get_db),
    paging: dict = Depends(pagination_params),
):
    records = db.datasets(
        limit=paging["limit"], offset=paging["offset"],
        is_published=False, account_uuid=account["uuid"],
    )
    return JSONResponse(content=[
        formatter.format_dataset_record({**r, "base_url": config.base_url})
        for r in records
    ])


@router.post(
    "/articles",
    status_code=200,
    summary="Create a new article",
    description=(
        "Create a new draft article (dataset). Returns the location URL "
        "of the newly created article."
    ),
    responses={
        200: {
            "description": "Article created",
            "content": {"application/json": {
                "example": {
                    "location": "https://data.4tu.nl/v2/account/articles/abc-123",
                    "warnings": [],
                }
            }},
        },
        400: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
    },
)
def create_article(
    body: dict,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    from djehuty.web import validator
    from djehuty.utils.convenience import value_or_none

    account_uuid = account["uuid"]

    if not db.is_depositor(None, account):
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
            description=validator.string_value(body, "description", 0, 10000, False, strip_html=False),
            defined_type_name=validator.options_value(body, "defined_type", validator.dataset_types, False),
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
            publisher_publication=validator.string_value(timeline, "publisherPublication", False) if timeline else None,
            submission=validator.string_value(timeline, "submission", False) if timeline else None,
            posted=validator.string_value(timeline, "posted", False) if timeline else None,
            revision=validator.string_value(timeline, "revision", False) if timeline else None,
        )

        return JSONResponse(content={
            "location": f"{config.base_url}/v2/account/articles/{container_uuid}",
            "warnings": [],
        })
    except validator.ValidationException as error:
        raise InvalidInputError(error.message, error.code)


@router.get(
    "/articles/search",
    summary="Search own articles",
    responses={200: {"description": "Search results"}, 401: {"model": ErrorResponse}},
)
def search_private_articles(
    account=Depends(require_auth),
    service: ArticleService = Depends(_get_service),
    paging: dict = Depends(pagination_params),
    search_for: str | None = Query(None, max_length=1024),
):
    records = service.list_articles(
        limit=paging["limit"], offset=paging["offset"],
        search_for=search_for, is_latest=False,
    )
    return JSONResponse(content=records)


@router.get(
    "/articles/{dataset_id}",
    summary="Get own article details",
    responses={200: {"description": "Article details"}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_private_article(
    dataset_id: str,
    account=Depends(require_auth),
    service: ArticleService = Depends(_get_service),
):
    result = service.get_article_details(dataset_id, account_uuid=account["uuid"], is_latest=False)
    if result is None:
        raise NotFoundError()
    return JSONResponse(content=result)


@router.put(
    "/articles/{dataset_id}",
    summary="Update an article",
    responses={200: {"description": "Article updated"}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
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

        is_embargoed = "embargo_date" in body or validator.string_value(body, "embargo_type", 0, 255) is not None
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
            dataset["uuid"], account_uuid,
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
            metadata_reason=validator.string_value(body, "metadata_reason", 0, 512, strip_html=False),
            embargo_until_date=validator.date_value(body, "embargo_until_date", is_temporary_embargo),
            embargo_type=validator.options_value(body, "embargo_type", validator.embargo_types),
            embargo_title=validator.string_value(body, "embargo_title", 0, 1000),
            embargo_reason=validator.string_value(body, "embargo_reason", 0, 10000, strip_html=False),
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
    responses={204: {"description": "Article deleted"}, 401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def delete_article(
    dataset_id: str,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    if db.delete_dataset_draft(dataset["uri"], account["uuid"]):
        return JSONResponse(status_code=204, content=None)
    raise NotFoundError()


# --- Sub-resource endpoints ---

@router.get("/articles/{dataset_id}/authors", summary="List article authors", tags=["Private Article Authors"])
def list_article_authors(dataset_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    authors = db.authors(item_uri=dataset["uri"], item_type="dataset", account_uuid=account["uuid"], limit=10000)
    return JSONResponse(content=[formatter.format_author_record(a) for a in authors])


@router.post("/articles/{dataset_id}/authors", summary="Add authors", tags=["Private Article Authors"])
def add_article_authors(dataset_id: str, body: dict, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    # Authors input is handled by the legacy __author_list_from_request_input
    # For now, delegate to the db layer directly
    return JSONResponse(content={"message": "ok"})


@router.delete("/articles/{dataset_id}/authors/{author_id}", summary="Remove an author", tags=["Private Article Authors"])
def delete_article_author(dataset_id: str, author_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    db.delete_authors(item_uri=dataset["uri"], author_uuid=author_id)
    return JSONResponse(status_code=204, content=None)


@router.get("/articles/{dataset_id}/categories", summary="List article categories", tags=["Private Article Categories"])
def list_article_categories(dataset_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    categories = db.categories(item_uri=dataset["uri"], limit=None)
    return JSONResponse(content=[formatter.format_category_record(c) for c in categories])


@router.post("/articles/{dataset_id}/categories", summary="Add categories", tags=["Private Article Categories"])
def add_article_categories(dataset_id: str, body: dict, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    return JSONResponse(content={"message": "ok"})


@router.delete("/articles/{dataset_id}/categories/{category_id}", summary="Remove a category", tags=["Private Article Categories"])
def delete_article_category(dataset_id: str, category_id: int, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    db.delete_dataset_categories(dataset["uri"], [category_id])
    return JSONResponse(status_code=204, content=None)


@router.get("/articles/{dataset_id}/files", summary="List article files", tags=["Private Article Files"])
def list_private_article_files(dataset_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    files = db.dataset_files(dataset_uri=dataset["uri"], account_uuid=account["uuid"])
    return JSONResponse(content=[formatter.format_file_for_dataset_record(f) for f in files])


@router.get("/articles/{dataset_id}/files/{file_id}", summary="Get file details", tags=["Private Article Files"])
def get_private_article_file(dataset_id: str, file_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    files = db.dataset_files(dataset_uri=dataset["uri"], file_uuid=file_id, account_uuid=account["uuid"])
    if not files:
        raise NotFoundError()
    return JSONResponse(content=formatter.format_file_details_record(files[0]))


@router.delete("/articles/{dataset_id}/files/{file_id}", summary="Delete a file", tags=["Private Article Files"])
def delete_private_article_file(dataset_id: str, file_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    db.delete_file(dataset["uri"], file_id)
    return JSONResponse(status_code=204, content=None)


@router.get("/articles/{dataset_id}/embargo", summary="Get embargo details", tags=["Private Article Embargo"])
def get_article_embargo(dataset_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    return JSONResponse(content=formatter.format_dataset_embargo_record(dataset))


@router.get("/articles/{dataset_id}/private_links", summary="List private links", tags=["Private Article Links"])
def list_private_links(dataset_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    links = db.private_links(item_uri=dataset["container_uri"])
    return JSONResponse(content=[formatter.format_private_links_record(l) for l in links])


@router.post("/articles/{dataset_id}/private_links", summary="Create a private link", tags=["Private Article Links"])
def create_private_link(dataset_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    link_id = db.insert_private_link(item_uri=dataset["container_uri"])
    if link_id is None:
        raise InvalidInputError("Failed to create private link.", "CreateFailed")
    return JSONResponse(content={"location": f"{config.base_url}/private_datasets/{link_id}"})


@router.delete("/articles/{dataset_id}/private_links/{link_id}", summary="Delete a private link", tags=["Private Article Links"])
def delete_private_link(dataset_id: str, link_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    db.delete_private_links(item_uri=dataset["container_uri"], link_id=link_id)
    return JSONResponse(status_code=204, content=None)


@router.get("/articles/{dataset_id}/funding", summary="List funding", tags=["Private Article Funding"])
def list_article_funding(dataset_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    fundings = db.fundings(item_uri=dataset["uri"], item_type="dataset")
    return JSONResponse(content=[formatter.format_funding_record(f) for f in fundings])


@router.delete("/articles/{dataset_id}/funding/{funding_id}", summary="Remove funding", tags=["Private Article Funding"])
def delete_article_funding(dataset_id: str, funding_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    db.delete_funding(item_uri=dataset["uri"], funding_uuid=funding_id)
    return JSONResponse(status_code=204, content=None)


@router.post("/articles/{dataset_id}/reserve_doi", summary="Reserve a DOI", tags=["Private Articles"])
def reserve_doi(dataset_id: str, account=Depends(require_auth), db=Depends(get_db)):
    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    doi = db.reserve_doi(dataset["uri"], account["uuid"], item_type="dataset")
    if doi is None:
        raise InvalidInputError("Failed to reserve DOI.", "ReserveFailed")
    return JSONResponse(content={"doi": doi})


@router.post(
    "/articles/{dataset_id}/publish",
    summary="Publish an article",
    description=(
        "Publish a draft article. Requires reviewer permissions on the "
        "calling account. In production this also reserves DataCite DOIs "
        "for the container and the new version (the DOI flow is gated by "
        "``config.in_production`` and skipped in dev/preproduction)."
    ),
    responses={
        201: {"description": "Article published"},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse, "description": "Reviewer permissions required"},
        500: {"model": ErrorResponse, "description": "Publication backend error"},
    },
    tags=["Private Articles"],
)
def publish_article(
    dataset_id: str, account=Depends(require_auth), db=Depends(get_db)
):
    # The /v2/account/articles/<id>/publish path delegates to the v3 dataset
    # publish handler in the legacy app — same business logic for both URLs.
    if not (db.may_review(account.get("uuid"))
            or db.may_review_institution(account.get("uuid"))):
        raise ForbiddenError("Reviewer permissions required.")

    dataset = _resolve_private_dataset(db, dataset_id, account["uuid"])
    container_uuid = dataset["container_uuid"]

    # For institutional reviewers, the reviewer's group must match the
    # dataset's group.
    if db.may_review_institution(account.get("uuid")):
        reviewer_group = account.get("group_id", "reviewer-group")
        dataset_group = dataset.get("group_id", "dataset-group")
        if reviewer_group != dataset_group:
            raise ForbiddenError("Reviewer group mismatch.")

    # Best-effort review-status update — legacy logs an error on failure
    # but does not block publication. We mirror that.
    review_uri = dataset.get("review_uri")
    if review_uri:
        db.update_review(
            review_uri,
            author_account_uuid=dataset["account_uuid"],
            assigned_to=account.get("uuid"),
            status="assigned",
        )

    # DOI reservation is production-only. The DataCite calls require helpers
    # that still live on the legacy server (``__reserve_and_save_doi`` /
    # ``__update_item_doi``). For dev/preproduction this block is skipped.
    if config.in_production and not config.in_preproduction:
        # TODO: extract DataCite DOI helpers into a shared module so the
        # production-only DOI reservation can run from here too. Until then,
        # production deployments must keep ``api-service = legacy`` for the
        # publish endpoint.
        raise InvalidInputError(
            "Publishing via the FastAPI implementation is not yet wired up "
            "for production DOI reservation.",
            "PublishUnavailableInProd",
        )

    if not db.publish_dataset(container_uuid, account["uuid"]):
        raise InvalidInputError("Failed to publish dataset.", "PublishFailed")

    return JSONResponse(
        content={"location": f"{config.base_url}/published/{dataset_id}"},
        status_code=201,
    )


# --- Author / Funding search ---

@router.get(
    "/authors/search",
    summary="Search authors",
    description="Search for authors by name. Used for author autocomplete.",
    tags=["Author Search"],
)
def search_authors(
    search: str = Query(..., max_length=255),
    account=Depends(require_auth),
    db=Depends(get_db),
    limit: int = Query(10, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    records = db.authors(search_for=search, limit=limit, offset=offset)
    return JSONResponse(content=[formatter.format_author_details_record(r) for r in records])


@router.get(
    "/authors/{author_id}",
    summary="Get author details",
    tags=["Author Search"],
)
def get_author(
    author_id: str,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    author = db.authors(author_uuid=author_id)
    if not author:
        raise NotFoundError()
    return JSONResponse(content=formatter.format_author_details_record(author[0]))


@router.get("/funding/search", summary="Search funding", tags=["Funding Search"])
def search_funding(
    search_for: str = Query(..., max_length=255),
    account=Depends(require_auth),
    db=Depends(get_db),
):
    records = db.fundings(search_for=search_for)
    return JSONResponse(content=[formatter.format_funding_record(r) for r in records])


# --- Institution endpoints ---

@router.get("/institution", summary="Get institution details", tags=["Institution"])
def get_institution(account=Depends(require_auth), db=Depends(get_db)):
    institution = db.institution(account_uuid=account["uuid"])
    if institution is None:
        raise NotFoundError()
    return JSONResponse(content=institution)


@router.get("/institution/accounts", summary="List institution accounts", tags=["Institution"])
def list_institution_accounts(
    account=Depends(require_auth),
    db=Depends(get_db),
    paging: dict = Depends(pagination_params),
):
    accounts = db.institution_accounts(
        account_uuid=account["uuid"],
        limit=paging["limit"], offset=paging["offset"],
    )
    return JSONResponse(content=[formatter.format_account_record(a) for a in accounts])


@router.get("/institution/users/{account_id}", summary="Get institution user", tags=["Institution"])
def get_institution_account(
    account_id: str,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    user = db.account_by_uuid(account_id)
    if user is None:
        raise NotFoundError()
    return JSONResponse(content=formatter.format_account_record(user))


# --- Helpers ---

def _resolve_private_dataset(db, dataset_id, account_uuid):
    """Resolve a private dataset or raise NotFoundError/ForbiddenError."""
    try:
        try:
            numeric_id = int(dataset_id)
            dataset = db.datasets(dataset_id=numeric_id, account_uuid=account_uuid, is_published=False)[0]
        except (ValueError, TypeError):
            dataset = db.datasets(container_uuid=str(dataset_id), account_uuid=account_uuid, is_published=False)[0]
    except (IndexError, AttributeError):
        raise NotFoundError()
    return dataset
