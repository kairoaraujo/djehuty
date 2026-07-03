"""Authenticated /v2/account/collections articles endpoints."""

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from djehuty.api.dependencies import get_db, pagination_params, require_auth
from djehuty.api.v2.account.collections._shared import _resolve_private_collection
from djehuty.web import formatter
from djehuty.web.config import config

router = APIRouter(tags=["V2 / Account / Collections / Articles"])


@router.get(
    "/account/collections/{collection_id}/articles",
    summary="List collection articles (private)",
)
def list_private_collection_articles(
    collection_id: str,
    account=Depends(require_auth),
    db=Depends(get_db),
    paging: dict = Depends(pagination_params),
):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    datasets = db.datasets(
        collection_uri=collection["uri"],
        is_latest=True,
        limit=paging["limit"],
        offset=paging["offset"],
    )
    return JSONResponse(
        content=[
            formatter.format_dataset_record({**r, "base_url": config.base_url}) for r in datasets
        ]
    )


@router.delete(
    "/account/collections/{collection_id}/articles/{article_id}",
    summary="Remove article from collection",
)
def delete_collection_article(
    collection_id: str, article_id: str, account=Depends(require_auth), db=Depends(get_db)
):
    collection = _resolve_private_collection(db, collection_id, account["uuid"])
    db.delete_collection_dataset(collection["uri"], article_id)
    return Response(status_code=204)
