"""Main v3 API router. Aggregates all v3 sub-routers."""

from fastapi import APIRouter

from djehuty.api.v3.datasets import router as datasets_router
from djehuty.api.v3.datasets_private import router as datasets_private_router
from djehuty.api.v3.profiles import router as profiles_router
from djehuty.api.v3.misc import router as misc_router

router = APIRouter(prefix="/v3", tags=["v3"])
router.include_router(datasets_router)
router.include_router(datasets_private_router)
router.include_router(profiles_router)
router.include_router(misc_router)
