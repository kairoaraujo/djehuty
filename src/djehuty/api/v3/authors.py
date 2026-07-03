"""Author lookup endpoints for the v3 API."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from djehuty.api.dependencies import get_db
from djehuty.api.exceptions import NotFoundError
from djehuty.api.v3._shared import _ok
from djehuty.web import formatter

router = APIRouter(tags=["V3 / Authors"])

_AUTHOR_DETAILS_EXAMPLE = {
    "first_name": "Ada",
    "full_name": "Ada Lovelace",
    "group_id": None,
    "id": None,
    "uuid": "07d6e6ce-b1bf-43ca-86e6-7a3ab8bc8416",
    "institution_id": None,
    "is_active": True,
    "is_public": True,
    "job_title": None,
    "last_name": "Lovelace",
    "orcid_id": "",
    "url_name": None,
}


@router.get(
    "/authors/{author_uuid}",
    summary="Get author details",
    responses={200: _ok("Author details", _AUTHOR_DETAILS_EXAMPLE)},
)
def get_author_details(author_uuid: str, db=Depends(get_db)):
    from djehuty.web import validator

    if not validator.is_valid_uuid(author_uuid):
        raise NotFoundError()

    records = db.authors(author_uuid=author_uuid)
    if not records:
        raise NotFoundError()
    return JSONResponse(content=formatter.format_author_details_record(records[0]))
