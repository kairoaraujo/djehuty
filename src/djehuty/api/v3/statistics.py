"""Dataset statistics endpoints for the v3 API."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from djehuty.api.dependencies import get_db
from djehuty.api.exceptions import InvalidInputError
from djehuty.api.models.common import ErrorResponse
from djehuty.api.v3._shared import _ok

router = APIRouter(tags=["V3 / Statistics"])

_TOP_EXAMPLE = [
    {
        "container_uuid": "27e6a01d-3f09-4d90-ae02-1d749ae9efb8",
        "dataset_id": 12873,
        "title": "Coastal water temperature measurements",
        "downloads": 4567,
        "figshare_url": "https://data.4tu.nl/articles/27e6a01d-3f09-4d90-ae02-1d749ae9efb8",
    }
]

_TIMELINE_EXAMPLE = [
    {"dataset_id": 12873, "date": "2026-05", "views": 214},
    {"dataset_id": 12873, "date": "2026-06", "views": 189},
]


@router.get(
    "/datasets/top/{item_type}",
    summary="Get top datasets by type",
    responses={
        200: _ok("Top datasets for the requested metric", _TOP_EXAMPLE),
        400: {"model": ErrorResponse, "description": "Invalid item_type"},
    },
)
def datasets_top(item_type: str, db=Depends(get_db), limit: int = Query(10, ge=1, le=100)):
    # AS-IS (#111): legacy validates item_type against this whitelist and so
    # rejects the documented default value "datasets" with 400.
    if item_type not in {"downloads", "views", "shares", "cites"}:
        raise InvalidInputError(
            "The last URL parameter must be one of 'downloads', 'views', 'shares' or 'cites'.",
            "InvalidURLParameterValue",
        )
    records = db.dataset_statistics(item_type=item_type, limit=limit)
    return JSONResponse(content=records)


@router.get(
    "/datasets/timeline/{item_type}",
    summary="Get dataset timeline",
    responses={
        200: _ok("Time-series counts for the requested metric", _TIMELINE_EXAMPLE),
        400: {"model": ErrorResponse, "description": "Invalid item_type"},
    },
)
def datasets_timeline(item_type: str, db=Depends(get_db)):
    # AS-IS (#111): legacy validates item_type against this whitelist and so
    # rejects the documented default value "datasets" with 400 (mirrors the
    # sibling /datasets/top/{item_type} handler above).
    if item_type not in {"downloads", "views", "shares", "cites"}:
        raise InvalidInputError(
            "The last URL parameter must be one of 'downloads', 'views', 'shares' or 'cites'.",
            "InvalidURLParameterValue",
        )
    records = db.dataset_statistics_timeline(item_type=item_type)
    return JSONResponse(content=records)
