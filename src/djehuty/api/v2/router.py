"""Main v2 API router. Aggregates all v2 sub-routers."""

from fastapi import APIRouter

from djehuty.api.v2.articles import router as articles_router
from djehuty.api.v2.articles_private import router as articles_private_router
from djehuty.api.v2.collections import router as collections_router
from djehuty.api.v2.misc import router as misc_router

router = APIRouter(prefix="/v2")
router.include_router(misc_router)
router.include_router(articles_router)
router.include_router(articles_private_router)
router.include_router(collections_router)
