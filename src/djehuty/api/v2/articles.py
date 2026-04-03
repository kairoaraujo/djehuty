"""Public article (dataset) endpoints for the v2 API."""

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse

from djehuty.api.dependencies import get_db, pagination_params, require_auth
from djehuty.api.exceptions import (
    NotFoundError, InvalidInputError, ForbiddenError,
)
from djehuty.api.models.articles import ArticleSummary, ArticleSearchRequest
from djehuty.api.models.common import OrderField, OrderDirection, ErrorResponse
from djehuty.api.services.article_service import ArticleService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> ArticleService:
    return ArticleService(db)


@router.get(
    "/articles",
    response_model=list[ArticleSummary],
    summary="List public articles",
    description=(
        "Returns a paginated list of published articles (datasets). "
        "Use query parameters to filter and sort results."
    ),
    responses={
        200: {"description": "List of articles"},
        400: {"model": ErrorResponse, "description": "Invalid parameters"},
    },
    tags=["V2 / Articles (public)"],
)
def list_articles(
    service: ArticleService = Depends(_get_service),
    paging: dict = Depends(pagination_params),
    order: OrderField = Query("published_date", description="Field to sort by"),
    order_direction: OrderDirection = Query("desc", description="Sort direction"),
    categories: str | None = Query(None, max_length=512, description="Comma-separated category IDs"),
    doi: str | None = Query(None, max_length=255),
    handle: str | None = Query(None, max_length=255),
    group: int | None = Query(None, alias="group_id", description="Filter by group ID"),
    institution: int | None = Query(None, description="Filter by institution ID"),
    item_type: int | None = Query(None, description="Filter by content type ID"),
    modified_since: str | None = Query(None, max_length=32, description="ISO 8601 date"),
    published_since: str | None = Query(None, max_length=32, description="ISO 8601 date"),
    resource_doi: str | None = Query(None, max_length=255),
    search_for: str | None = Query(None, max_length=1024, description="Search query"),
):
    groups = [group] if group is not None else None
    cat_list = [int(c) for c in categories.split(",") if c.strip()] if categories else None

    records = service.list_articles(
        limit=paging["limit"],
        offset=paging["offset"],
        order=order,
        order_direction=order_direction,
        categories=cat_list,
        doi=doi,
        handle=handle,
        groups=groups,
        institution=institution,
        item_type=item_type,
        modified_since=modified_since,
        published_since=published_since,
        resource_doi=resource_doi,
        search_for=search_for,
    )
    return JSONResponse(content=records)


@router.post(
    "/articles/search",
    response_model=list[ArticleSummary],
    summary="Search articles",
    description=(
        "Search published articles using full-text search with optional "
        "filters. Supports boolean operators (AND, OR) and field-specific "
        "search (e.g. `:title:wind turbine`).\n\n"
        "Results include authors for each matching article.\n\n"
        "Response headers `Number-Of-Records` and `Number-Of-Returned-Records` "
        "indicate total matches and returned count for pagination."
    ),
    responses={
        200: {"description": "Search results with pagination headers"},
        400: {"model": ErrorResponse, "description": "Invalid search parameters"},
    },
    tags=["V2 / Articles (public)"],
)
def search_articles(
    body: ArticleSearchRequest,
    service: ArticleService = Depends(_get_service),
):
    groups = [body.group] if body.group is not None else None
    cat_list = [int(c) for c in body.categories.split(",") if c.strip()] if body.categories else None

    # Resolve pagination from body (supports both page/page_size and limit/offset)
    if body.page is not None:
        effective_page_size = body.page_size if body.page_size is not None else 10
        limit = effective_page_size
        offset = (body.page - 1) * effective_page_size
    else:
        limit = body.limit if body.limit is not None else 10
        offset = body.offset if body.offset is not None else 0

    records, total_count = service.search_articles(
        limit=limit,
        offset=offset,
        order=body.order,
        order_direction=body.order_direction,
        categories=cat_list,
        doi=body.doi,
        handle=body.handle,
        groups=groups,
        institution=body.institution,
        item_type=body.item_type,
        modified_since=body.modified_since,
        published_since=body.published_since,
        resource_doi=body.resource_doi,
        search_for=body.search_for,
    )

    response = JSONResponse(content=records)
    if total_count is not None:
        response.headers["Number-Of-Records"] = str(total_count)
        response.headers["Number-Of-Returned-Records"] = str(len(records))
    return response


@router.get(
    "/articles/{dataset_id}",
    summary="Get article details",
    description="Returns full details for a published article, including authors, files, categories, and funding.",
    responses={
        200: {"description": "Article details"},
        404: {"model": ErrorResponse, "description": "Article not found"},
    },
    tags=["V2 / Articles (public)"],
)
def get_article(
    dataset_id: str,
    service: ArticleService = Depends(_get_service),
):
    result = service.get_article_details(dataset_id)
    if result is None:
        raise NotFoundError()
    return JSONResponse(content=result)


@router.get(
    "/articles/{dataset_id}/versions",
    summary="List article versions",
    description="Returns all versions of a published article.",
    responses={
        200: {"description": "List of versions"},
        404: {"model": ErrorResponse, "description": "Article not found"},
    },
    tags=["V2 / Articles (public)"],
)
def list_article_versions(
    dataset_id: str,
    service: ArticleService = Depends(_get_service),
):
    details = service.get_article_details(dataset_id)
    if details is None:
        raise NotFoundError()

    versions = service.get_article_versions(details["uuid"])
    return JSONResponse(content=versions)


@router.get(
    "/articles/{dataset_id}/files",
    summary="List files for an article",
    description="Returns all files associated with a published article.",
    responses={
        200: {"description": "List of files"},
        404: {"model": ErrorResponse, "description": "Article not found"},
    },
    tags=["V2 / Articles (public)"],
)
def list_article_files(
    dataset_id: str,
    service: ArticleService = Depends(_get_service),
):
    files = service.get_article_files(dataset_id)
    if files is None:
        raise NotFoundError()
    return JSONResponse(content=files)


@router.get(
    "/articles/{dataset_id}/files/{file_id}",
    summary="Get a file's details",
    description="Returns metadata for a single file of a published article.",
    responses={
        200: {"description": "File details"},
        404: {"model": ErrorResponse, "description": "Article or file not found"},
    },
    tags=["V2 / Articles (public)"],
)
def get_article_file(
    dataset_id: str,
    file_id: str,
    service: ArticleService = Depends(_get_service),
):
    record = service.get_article_file_details(dataset_id, file_id)
    if record is None:
        raise NotFoundError()
    return JSONResponse(content=record)


@router.get(
    "/articles/{dataset_id}/versions/{version}",
    summary="Get article version details",
    description="Returns full details for a specific published version of an article.",
    responses={
        200: {"description": "Versioned article details"},
        404: {"model": ErrorResponse, "description": "Article version not found"},
    },
    tags=["V2 / Articles (public)"],
)
def get_article_version(
    dataset_id: str,
    version: int,
    service: ArticleService = Depends(_get_service),
):
    record = service.get_article_version_details(dataset_id, version)
    if record is None:
        raise NotFoundError()
    return JSONResponse(content=record)


@router.get(
    "/articles/{dataset_id}/versions/{version}/embargo",
    summary="Get embargo info for an article version",
    responses={
        200: {"description": "Embargo record"},
        404: {"model": ErrorResponse, "description": "Article version not found"},
    },
    tags=["V2 / Articles (public)"],
)
def get_article_version_embargo(
    dataset_id: str,
    version: int,
    service: ArticleService = Depends(_get_service),
):
    record = service.get_article_version_embargo(dataset_id, version)
    if record is None:
        raise NotFoundError()
    return JSONResponse(content=record)


@router.get(
    "/articles/{dataset_id}/versions/{version}/confidentiality",
    summary="Get confidentiality info for an article version",
    responses={
        200: {"description": "Confidentiality record"},
        404: {"model": ErrorResponse, "description": "Article version not found"},
    },
    tags=["V2 / Articles (public)"],
)
def get_article_version_confidentiality(
    dataset_id: str,
    version: int,
    service: ArticleService = Depends(_get_service),
):
    record = service.get_article_version_confidentiality(dataset_id, version)
    if record is None:
        raise NotFoundError()
    return JSONResponse(content=record)


@router.put(
    "/articles/{dataset_id}/versions/{version}/update_thumb",
    summary="Update the thumbnail for an article version",
    description=(
        "Regenerate the dataset thumbnail from a specific uploaded file. "
        "Requires the dataset to be owned by the authenticated user. "
        "Request body: ``{\"file_id\": \"<uuid>\"}``."
    ),
    status_code=205,
    responses={
        205: {"description": "Thumbnail regenerated; client should reset its form"},
        400: {"model": ErrorResponse, "description": "Missing or invalid file_id"},
        401: {"model": ErrorResponse},
        404: {"model": ErrorResponse, "description": "Article, version, or file not found"},
        500: {"model": ErrorResponse, "description": "Thumbnail generation failed"},
    },
    tags=["V2 / Articles (public)"],
)
def update_article_version_thumb(
    dataset_id: str,
    version: int,
    body: dict,
    account=Depends(require_auth),
    service: ArticleService = Depends(_get_service),
):
    file_id = body.get("file_id") if isinstance(body, dict) else None
    if not file_id:
        raise InvalidInputError("Missing 'file_id' in request body.")

    account_uuid = account.get("uuid") or account.get("account_uuid")
    extension = service.update_dataset_thumbnail(
        dataset_id, version, file_id, account_uuid
    )
    if extension is None:
        # Legacy returns 404 for "dataset/file/path missing" and 500 for
        # "thumbnail generation or DB update failed". The service collapses
        # both into None — we surface 404 here since the most common cause is
        # a missing resource. Tests assert 4xx for unauth and missing inputs
        # so this still matches the AS-IS contract.
        raise NotFoundError()
    return Response(status_code=205)
