from fastapi import APIRouter

from app.api.v1 import analytics, auth, catalog, feedback, imports, integrations, intelligence, reports, topics, workspaces

api_router = APIRouter(prefix="/api/v1")
for module in (auth, workspaces, catalog, feedback, imports, topics, analytics, intelligence, reports, integrations):
    api_router.include_router(module.router)
