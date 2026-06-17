"""Miscellaneous v3 endpoints: tags, groups, accounts, authors, RO-Crates,
codemeta, DOI badges, profile pictures, single-file detail."""

import re
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import FileResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from djehuty.web import formatter
from djehuty.web.config import config
from djehuty.api.dependencies import get_db, require_auth
from djehuty.api.exceptions import InvalidInputError, NotFoundError, ForbiddenError

router = APIRouter()


# Jinja env for the badge.svg template rendered by the DOI-badge endpoints.
_TEMPLATE_DIR = (
    Path(__file__).resolve().parents[2] / "web" / "resources" / "html_templates"
)
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "svg"]),
)


@router.post("/tags/search", summary="Search tags", tags=["Tags"])
def search_tags(body: dict, db=Depends(get_db)):
    # Legacy reads ``search_for`` from the JSON body (POST).
    search_for = body.get("search_for") if isinstance(body, dict) else None
    if not isinstance(search_for, str) or len(search_for) > 32:
        raise InvalidInputError(
            "Field 'search_for' is required and must be a string of <= 32 chars.",
            "BadSearchFor",
        )
    tags = db.previously_used_tags(search_for)
    tag_values = [item["tag"] if isinstance(item, dict) else item for item in tags]
    return JSONResponse(content=tag_values)


@router.get("/groups", summary="List institutional groups", tags=["Groups"])
def list_groups(db=Depends(get_db)):
    records = db.group()
    return JSONResponse(content=[formatter.format_group_record(r) for r in records])


@router.post(
    "/accounts/search",
    summary="Search accounts",
    description="Search for user accounts. Requires reviewer privileges.",
    tags=["Accounts"],
)
def search_accounts(
    body: dict,
    account=Depends(require_auth),
    db=Depends(get_db),
):
    # Legacy reads the filter dict from the JSON body (POST).
    if not isinstance(body, dict):
        body = {}
    records = db.accounts(
        search_for=body.get("search_for"),
        limit=body.get("limit", 10),
        offset=body.get("offset", 0),
    )
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


@router.get(
    "/datasets/{container_uuid}/versions/{version}/ro-crate-metadata.json",
    summary="Get RO-Crate metadata for a specific dataset version",
    tags=["RO-Crates"],
)
def get_versioned_ro_crate_metadata(
    container_uuid: str, version: int, db=Depends(get_db),
):
    from djehuty.web import validator

    if not validator.is_valid_uuid(container_uuid):
        raise NotFoundError()
    try:
        dataset = db.datasets(
            container_uuid=container_uuid,
            is_published=True,
            is_latest=False,
            version=version,
            limit=1,
        )[0]
    except (IndexError, AttributeError):
        raise NotFoundError()

    dataset_uri = dataset["uri"]
    record = formatter.format_rocrate_record(
        base_url=config.base_url,
        site_name=config.site_name,
        record=dataset,
        ror_url=config.ror_url,
        tags=db.tags(item_uri=dataset_uri),
        files=db.dataset_files(dataset_uri=dataset_uri),
        authors=db.authors(item_uri=dataset_uri, item_type="dataset"),
    )
    return JSONResponse(content=record)


# ---------------------------------------------------------------------------
# /v3/codemeta — published software in codemeta format
# ---------------------------------------------------------------------------

@router.get("/codemeta", summary="List published software in codemeta format")
def list_codemeta(
    db=Depends(get_db),
    limit: int | None = Query(None, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    order: str | None = Query(None, max_length=255),
    order_direction: str | None = Query(None, pattern="^(asc|desc)$"),
    modified_since: str | None = Query(None, max_length=32),
    doi: str | None = Query(None, max_length=255),
):
    datasets = db.datasets(
        is_published=True,
        is_latest=True,
        is_software=True,
        is_embargoed=False,
        is_restricted=False,
        doi=doi,
        modified_since=modified_since,
        order=order,
        order_direction=order_direction,
        limit=limit,
        offset=offset,
    )
    output = []
    for dataset in datasets:
        has_files = bool(db.dataset_files(dataset_uri=dataset["uri"], limit=1))
        output.append(
            formatter.format_codemeta_record(
                dataset,
                tags=db.tags(item_uri=dataset["uri"], limit=None),
                authors=db.authors(
                    item_uri=dataset["uri"],
                    is_published=True,
                    item_type="dataset",
                    limit=10000,
                ),
                has_files=has_files,
                base_url=config.base_url,
            )
        )
    return JSONResponse(content=output)


# ---------------------------------------------------------------------------
# DOI badges — SVG image rendered from the badge.svg template
# ---------------------------------------------------------------------------

def _render_doi_badge(db, dataset_id: str, version: int | None) -> Response:
    from djehuty.web import validator
    try:
        if validator.is_valid_uuid(dataset_id):
            params: dict = {"container_uuid": dataset_id, "limit": 1}
        else:
            try:
                params = {"dataset_id": int(dataset_id), "limit": 1}
            except (ValueError, TypeError):
                raise NotFoundError()

        if version is not None:
            params["version"] = version
            params["is_latest"] = False
        else:
            params["is_latest"] = True

        dataset = db.datasets(**params)[0]
        doi = dataset["container_doi"] if version is None else dataset["doi"]
        body = _jinja_env.get_template("badge.svg").render(
            doi=doi,
            version=version,
            color=config.colors.get("primary-color", "#000000"),
        )
        return Response(content=body, media_type="image/svg+xml")
    except (IndexError, KeyError, AttributeError):
        raise NotFoundError()


@router.get(
    "/datasets/{dataset_id}/doi-badge.svg",
    summary="DOI badge SVG (latest version)",
    tags=["Datasets"],
)
def get_doi_badge(dataset_id: str, db=Depends(get_db)):
    return _render_doi_badge(db, dataset_id, version=None)


@router.get(
    "/datasets/{dataset_id}/doi-badge-v{version}.svg",
    summary="DOI badge SVG for a specific version",
    tags=["Datasets"],
)
def get_doi_badge_versioned(dataset_id: str, version: int, db=Depends(get_db)):
    return _render_doi_badge(db, dataset_id, version=version)


# ---------------------------------------------------------------------------
# /v3/file/<id> — single-file metadata (auth-required)
# ---------------------------------------------------------------------------

@router.get("/file/{file_id}", summary="Get file details by id")
def get_file_details(
    file_id: str, account=Depends(require_auth), db=Depends(get_db),
):
    account_uuid = account["uuid"]
    try:
        records = db.dataset_files(
            file_uuid=file_id, account_uuid=account_uuid, limit=1,
        )
        metadata = records[0]
    except (IndexError, AttributeError, TypeError):
        raise NotFoundError()
    try:
        metadata["base_url"] = config.base_url
        return JSONResponse(content=formatter.format_file_details_record(metadata))
    except KeyError:
        raise NotFoundError()
