"""Institutional group endpoints for the v3 API."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from djehuty.api.dependencies import get_db
from djehuty.api.v3._shared import _ok
from djehuty.web import formatter

router = APIRouter(tags=["V3 / Groups"])

_GROUPS_EXAMPLE = [
    {
        "id": 28585,
        "parent_id": 0,
        "name": "4TU.ResearchData",
        "association": "4tu.nl",
        "is_featured": False,
    },
    {
        "id": 28586,
        "parent_id": 28585,
        "name": "Delft University of Technology",
        "association": "tudelft.nl",
        "is_featured": True,
    },
]


@router.get(
    "/groups",
    summary="List institutional groups",
    responses={200: _ok("Institutional groups", _GROUPS_EXAMPLE)},
)
def list_groups(db=Depends(get_db)):
    records = db.group()
    return JSONResponse(content=[formatter.format_group_record(r) for r in records])
