"""Miscellaneous v3 endpoints: tags, groups, accounts, authors, RO-Crates."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from djehuty.web import formatter
from djehuty.web.config import config
from djehuty.api.dependencies import get_db, require_auth
from djehuty.api.exceptions import NotFoundError

router = APIRouter()


@router.get("/tags/search", summary="Search tags", tags=["Tags"])
def search_tags(
    search: str = Query(..., max_length=255, description="Tag search term"),
    db=Depends(get_db),
    limit: int = Query(10, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    records = db.tags(limit=limit)
    return JSONResponse(content=[formatter.format_tag_record(r) for r in records])


@router.get("/groups", summary="List institutional groups", tags=["Groups"])
def list_groups(db=Depends(get_db)):
    records = db.group()
    return JSONResponse(content=[formatter.format_group_record(r) for r in records])


@router.get(
    "/accounts/search",
    summary="Search accounts",
    description="Search for user accounts by name. Requires authentication.",
    tags=["Accounts"],
)
def search_accounts(
    search: str = Query(..., max_length=255),
    account=Depends(require_auth),
    db=Depends(get_db),
    limit: int = Query(10, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    records = db.accounts(search_for=search, limit=limit, offset=offset)
    return JSONResponse(content=[formatter.format_account_record(r) for r in records])


@router.get("/authors/{author_uuid}", summary="Get author details", tags=["Authors"])
def get_author_details(author_uuid: str, db=Depends(get_db)):
    from djehuty.web import validator
    if not validator.is_valid_uuid(author_uuid):
        raise NotFoundError()

    records = db.authors(author_uuid=author_uuid)
    if not records:
        raise NotFoundError()
    return JSONResponse(content=formatter.format_author_details_record(records[0]))


@router.get("/ro-crates", summary="List RO-Crate enabled datasets", tags=["RO-Crates"])
def list_ro_crates(db=Depends(get_db)):
    records = db.datasets(is_latest=True, limit=100)
    uuids = [r.get("container_uuid") for r in records if r.get("container_uuid")]
    return JSONResponse(content=uuids)


@router.get(
    "/datasets/{container_uuid}/ro-crate-metadata.json",
    summary="Get RO-Crate metadata for a dataset",
    tags=["RO-Crates"],
)
def get_ro_crate_metadata(container_uuid: str, db=Depends(get_db)):
    from djehuty.web import validator
    if not validator.is_valid_uuid(container_uuid):
        raise NotFoundError()

    try:
        dataset = db.datasets(container_uuid=container_uuid, is_latest=True)[0]
    except (IndexError, AttributeError):
        raise NotFoundError()

    dataset_uri = dataset["uri"]
    authors = db.authors(item_uri=dataset_uri, item_type="dataset")
    files = db.dataset_files(dataset_uri=dataset_uri)
    tags = db.tags(item_uri=dataset_uri)

    record = formatter.format_rocrate_record(
        base_url=config.base_url,
        site_name=config.site_name,
        record=dataset,
        ror_url=config.ror_url,
        tags=tags,
        files=files,
        authors=authors,
    )
    return JSONResponse(content=record)
