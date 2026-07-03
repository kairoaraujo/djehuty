"""Authenticated /v2/account/collections funding endpoints."""

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from djehuty.api.dependencies import get_db, require_auth
from djehuty.api.v2.account.collections._shared import _resolve_private_collection
from djehuty.web import formatter

router = APIRouter(tags=["V2 / Account / Collections / Funding"])


@router.get(
    "/account/collections/{collection_id}/funding",
    summary="List funding",
)
def list_collection_funding(collection_id: str, account=Depends(require_auth), db=Depends(get_db)):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    fundings = db.fundings(item_uri=collection["uri"], item_type="collection")
    return JSONResponse(content=[formatter.format_funding_record(f) for f in fundings])


@router.delete(
    "/account/collections/{collection_id}/funding/{funding_id}",
    summary="Remove funding",
)
def delete_collection_funding(
    collection_id: str, funding_id: str, account=Depends(require_auth), db=Depends(get_db)
):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    db.delete_funding(item_uri=collection["uri"], funding_uuid=funding_id)
    return Response(status_code=204)
