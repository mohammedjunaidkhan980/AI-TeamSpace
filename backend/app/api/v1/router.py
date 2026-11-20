from fastapi import APIRouter

from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.agents import (
    group_agents_router,
    templates_router as agent_templates_router,
)
from app.api.v1.endpoints.connections import router as connections_router
from app.api.v1.endpoints.documents import (
    documents_router,
    group_documents_router,
)
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.groups import router as groups_router
from app.api.v1.endpoints.messages import (
    group_router as group_messages_router,
    message_router,
    webhook_router as webhook_messages_router,
)
from app.api.v1.endpoints.nexconn import router as nexconn_router
from app.api.v1.endpoints.notifications import router as notifications_router
from app.api.v1.endpoints.users import router as users_router

router = APIRouter()
router.include_router(health_router, tags=["health"])
router.include_router(auth_router, prefix="/auth", tags=["authentication"])
router.include_router(users_router, prefix="/users", tags=["users"])
router.include_router(
    connections_router,
    prefix="/connections",
    tags=["connections"],
)
router.include_router(documents_router, prefix="/documents", tags=["documents"])
router.include_router(
    group_documents_router, prefix="/groups", tags=["documents"]
)
router.include_router(groups_router, prefix="/groups", tags=["groups"])
router.include_router(
    group_messages_router,
    prefix="/groups",
    tags=["messages"],
)
router.include_router(message_router, prefix="/messages", tags=["messages"])
router.include_router(
    webhook_messages_router,
    prefix="/webhooks",
    tags=["Nexconn webhooks"],
)
router.include_router(nexconn_router, prefix="/nexconn", tags=["Nexconn"])
router.include_router(
    notifications_router, prefix="/notifications", tags=["notifications"]
)
router.include_router(agent_templates_router, prefix="/agents", tags=["agents"])
router.include_router(group_agents_router, prefix="/groups", tags=["agents"])
