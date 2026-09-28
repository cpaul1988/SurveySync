"""Open-source integration routes for SurveySync 9.4.

This router keeps optional point-cloud and declarative workflow endpoints outside
the frozen main router.
"""

from fastapi import APIRouter

from .pointcloud_routes import router as pointcloud_router
from .workflow_routes import router as workflow_router
from .crs_diagnostic_routes import router as crs_diagnostic_router
from .report_template_routes import router as report_template_router
from .gis_bridge_routes import router as gis_bridge_router

router = APIRouter()
router.include_router(pointcloud_router)
router.include_router(workflow_router)
router.include_router(crs_diagnostic_router)
router.include_router(report_template_router)
router.include_router(gis_bridge_router)

from .visual_qa_routes import router as visual_qa_router

router.include_router(visual_qa_router)
