"""Capability inventory kept outside the frozen project router."""

from fastapi import APIRouter

from .integration_registry import inventory

router = APIRouter(prefix="/api/v9/integrations")


@router.get("/status")
def status():
    return inventory()
