"""Prevent a stale desktop panel from operating on a different project."""
from fastapi import HTTPException, Request


def require_panel_project(request: Request):
    from . import router as context
    project = context.require_project()
    expected = request.headers.get("X-SurveySync-Project")
    if expected is not None and expected != str(project.manifest.get("project_id", "")):
        raise HTTPException(409, "Project changed. Reopen the panel before continuing.")
    return project
