"""Public and private collection endpoints for the v2 API."""

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse

from djehuty.web import formatter
from djehuty.web.config import config
from djehuty.api.dependencies import get_db, require_auth, pagination_params
from djehuty.api.exceptions import NotFoundError, InvalidInputError
from djehuty.api.models.collections import CollectionSummary, CollectionSearchRequest
from djehuty.api.models.common import OrderField, OrderDirection, ErrorResponse
from djehuty.api.services.collection_service import CollectionService

router = APIRouter()


def _get_service(db=Depends(get_db)) -> CollectionService:
    return CollectionService(db)


# --- Public endpoints ---

@router.get(
    "/collections",
    response_model=list[CollectionSummary],
    summary="List public collections",
    tags=["Collections"],
)
def list_collections(
    service: CollectionService = Depends(_get_service),
    paging: dict = Depends(pagination_params),
    order: OrderField = Query("published_date"),
    order_direction: OrderDirection = Query("desc"),
):
    records = service.list_collections(
        limit=paging["limit"], offset=paging["offset"],
        order=order, order_direction=order_direction,
    )
    return JSONResponse(content=records)


@router.post(
    "/collections/search",
    response_model=list[CollectionSummary],
    summary="Search collections",
    tags=["Collections"],
)
def search_collections(
    body: CollectionSearchRequest,
    service: CollectionService = Depends(_get_service),
):
    limit = body.limit or 10
    offset = body.offset or 0
    if body.page is not None:
        ps = body.page_size or 10
        limit, offset = ps, (body.page - 1) * ps

    records, _ = service.search_collections(
        limit=limit, offset=offset,
        order=body.order, order_direction=body.order_direction,
        search_for=body.search_for,
    )
    return JSONResponse(content=records)


@router.get("/collections/{collection_id}", summary="Get collection details", tags=["Collections"])
def get_collection(collection_id: str, service: CollectionService = Depends(_get_service)):
    result = service.get_collection_details(collection_id)
    if result is None:
        raise NotFoundError()
    return JSONResponse(content=result)


@router.get("/collections/{collection_id}/versions", summary="List collection versions", tags=["Collections"])
def list_collection_versions(collection_id: str, service: CollectionService = Depends(_get_service)):
    details = service.get_collection_details(collection_id)
    if details is None:
        raise NotFoundError()
    versions = service.get_collection_versions(details["uuid"])
    return JSONResponse(content=versions)


@router.get("/collections/{collection_id}/versions/{version}", summary="Get collection version", tags=["Collections"])
def get_collection_version(collection_id: str, version: int, service: CollectionService = Depends(_get_service)):
    details = service.get_collection_details(collection_id, is_latest=False)
    if details is None:
        raise NotFoundError()
    return JSONResponse(content=details)


@router.get("/collections/{collection_id}/articles", summary="List collection articles", tags=["Collections"])
def list_collection_articles(
    collection_id: str,
    service: CollectionService = Depends(_get_service),
    paging: dict = Depends(pagination_params),
):
    datasets = service.get_collection_datasets(collection_id, limit=paging["limit"], offset=paging["offset"])
    if datasets is None:
        raise NotFoundError()
    return JSONResponse(content=datasets)


# --- Private (authenticated) endpoints ---

@router.post(
    "/account/collections",
    status_code=200,
    summary="Create a new draft collection",
    tags=["Private Collections"],
)
def create_collection(
    body: dict,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    from djehuty.utils.convenience import value_or_none
    from djehuty.web import validator

    try:
        group_id = validator.integer_value(body, "group_id", 0, pow(2, 63), False)
        if group_id is None:
            acct = db.account_by_uuid(account["uuid"])
            group_id = value_or_none(acct, "group_id")

        publisher = validator.string_value(body, "publisher", 0, 255, False)
        if publisher is None:
            publisher = config.site_name

        container_uuid, _ = db.insert_collection(
            title=validator.string_value(body, "title", 3, 1000, True),
            account_uuid=account["uuid"],
            description=validator.string_value(body, "description", 0, 10000, False, strip_html=False),
            funding=validator.string_value(body, "funding", 0, 255, False),
            language=validator.string_value(body, "language", 0, 8, False),
            doi=validator.string_value(body, "doi", 0, 255, False),
            handle=validator.string_value(body, "handle", 0, 255, False),
            resource_doi=validator.string_value(body, "resource_doi", 0, 255, False),
            resource_title=validator.string_value(body, "resource_title", 0, 255, False),
            group_id=group_id,
            publisher=publisher,
            custom_fields=validator.object_value(body, "custom_fields", False),
            custom_fields_list=validator.array_value(body, "custom_fields_list", False),
        )
        return JSONResponse(content={
            "location": f"{config.base_url}/v2/account/collections/{container_uuid}",
            "warnings": [],
        })
    except validator.ValidationException as error:
        raise InvalidInputError(error.message, error.code)


@router.delete(
    "/account/collections/{collection_id}",
    summary="Delete a draft collection",
    tags=["Private Collections"],
)
def delete_collection(
    collection_id: str,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    if not db.delete_collection_draft(collection["container_uuid"], account["uuid"]):
        raise InvalidInputError("Failed to delete collection.", "DeleteFailed")
    return Response(status_code=204)


@router.get("/account/collections", summary="List own draft collections", tags=["Private Collections"])
def list_private_collections(
    account=Depends(require_auth),
    service: CollectionService = Depends(_get_service),
    paging: dict = Depends(pagination_params),
):
    records = service.list_collections(
        limit=paging["limit"], offset=paging["offset"],
        is_latest=False, account_uuid=account["uuid"],
    )
    return JSONResponse(content=records)


@router.post("/account/collections/search", summary="Search own collections", tags=["Private Collections"])
def search_private_collections(
    body: CollectionSearchRequest,
    account=Depends(require_auth),
    service: CollectionService = Depends(_get_service),
):
    limit = body.limit or 10
    offset = body.offset or 0

    records, _ = service.search_collections(
        limit=limit, offset=offset,
        order=body.order, order_direction=body.order_direction,
        search_for=body.search_for, account_uuid=account["uuid"],
    )
    return JSONResponse(content=records)


@router.get("/account/collections/{collection_id}", summary="Get own collection details", tags=["Private Collections"])
def get_private_collection(
    collection_id: str,
    account=Depends(require_auth),
    service: CollectionService = Depends(_get_service),
):
    result = service.get_collection_details(collection_id, account_uuid=account["uuid"], is_latest=False)
    if result is None:
        raise NotFoundError()
    return JSONResponse(content=result)


@router.get("/account/collections/{collection_id}/authors", summary="List collection authors", tags=["Private Collection Authors"])
def list_collection_authors(collection_id: str, account=Depends(require_auth), db=Depends(get_db)):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    authors = db.authors(item_uri=collection["uri"], item_type="collection", account_uuid=account["uuid"], limit=10000)
    return JSONResponse(content=[formatter.format_author_record(a) for a in authors])


@router.delete("/account/collections/{collection_id}/authors/{author_id}", summary="Remove author", tags=["Private Collection Authors"])
def delete_collection_author(collection_id: str, author_id: str, account=Depends(require_auth), db=Depends(get_db)):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    db.delete_authors(item_uri=collection["uri"], author_uuid=author_id)
    return Response(status_code=204)


@router.get("/account/collections/{collection_id}/categories", summary="List collection categories", tags=["Private Collection Categories"])
def list_collection_categories(collection_id: str, account=Depends(require_auth), db=Depends(get_db)):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    categories = db.categories(item_uri=collection["uri"], limit=None)
    return JSONResponse(content=[formatter.format_category_record(c) for c in categories])


@router.delete("/account/collections/{collection_id}/categories/{category_id}", summary="Remove category", tags=["Private Collection Categories"])
def delete_collection_category(collection_id: str, category_id: int, account=Depends(require_auth), db=Depends(get_db)):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    db.delete_collection_categories(collection["uri"], [category_id])
    return Response(status_code=204)


@router.get("/account/collections/{collection_id}/articles", summary="List collection articles (private)", tags=["Private Collection Articles"])
def list_private_collection_articles(collection_id: str, account=Depends(require_auth), db=Depends(get_db), paging: dict = Depends(pagination_params)):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    datasets = db.collection_datasets(container_uri=collection["container_uri"], limit=paging["limit"], offset=paging["offset"])
    return JSONResponse(content=[formatter.format_dataset_record({**r, "base_url": config.base_url}) for r in datasets])


@router.delete("/account/collections/{collection_id}/articles/{article_id}", summary="Remove article from collection", tags=["Private Collection Articles"])
def delete_collection_article(collection_id: str, article_id: str, account=Depends(require_auth), db=Depends(get_db)):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    db.delete_collection_dataset(collection["uri"], article_id)
    return Response(status_code=204)


@router.get("/account/collections/{collection_id}/funding", summary="List funding", tags=["Private Collection Funding"])
def list_collection_funding(collection_id: str, account=Depends(require_auth), db=Depends(get_db)):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    fundings = db.fundings(item_uri=collection["uri"], item_type="collection")
    return JSONResponse(content=[formatter.format_funding_record(f) for f in fundings])


@router.delete("/account/collections/{collection_id}/funding/{funding_id}", summary="Remove funding", tags=["Private Collection Funding"])
def delete_collection_funding(collection_id: str, funding_id: str, account=Depends(require_auth), db=Depends(get_db)):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    db.delete_funding(item_uri=collection["uri"], funding_uuid=funding_id)
    return Response(status_code=204)


@router.post("/account/collections/{collection_id}/reserve_doi", summary="Reserve DOI", tags=["Private Collections"])
def reserve_collection_doi(collection_id: str, account=Depends(require_auth), db=Depends(get_db)):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    doi = db.reserve_doi(collection["uri"], account["uuid"], item_type="collection")
    if doi is None:
        raise InvalidInputError("Failed to reserve DOI.", "ReserveFailed")
    return JSONResponse(content={"doi": doi})


def _resolve_private_collection(db, collection_id, account_uuid):
    """Resolve a private collection or raise NotFoundError."""
    try:
        try:
            numeric_id = int(collection_id)
            return db.collections(collection_id=numeric_id, account_uuid=account_uuid, is_published=False)[0]
        except (ValueError, TypeError):
            return db.collections(container_uuid=str(collection_id), account_uuid=account_uuid, is_published=False)[0]
    except (IndexError, AttributeError):
        raise NotFoundError()
