"""Authenticated /v2/account/collections categories endpoints."""

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from djehuty.api.dependencies import get_db, require_auth
from djehuty.api.v2.account.collections._shared import _resolve_private_collection
from djehuty.web import formatter

router = APIRouter(tags=["V2 / Account / Collections / Categories"])


@router.get(
    "/account/collections/{collection_id}/categories",
    summary="List collection categories",
)
def list_collection_categories(
    collection_id: str, account=Depends(require_auth), db=Depends(get_db)
):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    categories = db.categories(item_uri=collection["uri"], limit=None)
    return JSONResponse(content=[formatter.format_category_record(c) for c in categories])


@router.delete(
    "/account/collections/{collection_id}/categories/{category_id}",
    summary="Remove category",
)
def delete_collection_category(
    collection_id: str, category_id: int, account=Depends(require_auth), db=Depends(get_db)
):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    db.delete_collection_categories(collection["uri"], [category_id])
    return Response(status_code=204)
