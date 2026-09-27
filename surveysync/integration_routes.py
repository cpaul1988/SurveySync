"""Open-source integration routes for SurveySync 9.4.

This router keeps optional point-cloud and declarative workflow endpoints outside
the frozen main router.
"""

from fastapi import APIRouter

from .operations_routes import router as operations_router
from .pointcloud_routes import router as pointcloud_router
from .workflow_routes import router as workflow_router

router = APIRouter()
router.include_router(operations_router)
router.include_router(pointcloud_router)
router.include_router(workflow_router)
