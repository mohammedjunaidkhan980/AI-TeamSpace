from typing import Annotated, Any

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pymongo.database import Database

from app.core.security import get_current_user
from app.database.mongodb import get_database
from app.repositories.agents import (
    DuplicateGroupAgentError,
    create_group_agent,
    get_group_agent,
    list_group_agents,
    set_group_agent_enabled,
    soft_delete_group_agent,
    sync_group_agent_summary,
    update_group_agent,
)
from app.repositories.groups import get_group, get_member_role, valid_object_id
from app.schemas.agents import (
    AgentStatusUpdate,
    AgentTemplate,
    CreateGroupAgent,
    GroupAgentListResponse,
    GroupAgentResponse,
    UpdateGroupAgent,
)
from app.schemas.auth import AuthenticatedUser
from app.services.agent_templates import get_agent_template, get_agent_templates

templates_router = APIRouter()
group_agents_router = APIRouter()


async def _require_group_role(
    database: Database[dict[str, Any]],
    *,
    group_id: str,
    user_id: str,
    admin: bool = False,
) -> tuple[dict[str, Any], str]:
    group = await get_group(database, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    role = get_member_role(group, user_id)
    if role is None:
        raise HTTPException(status_code=403, detail="Group membership required")
    if admin and role != "admin":
        raise HTTPException(status_code=403, detail="Group admin role required")
    return group, role


def _agent_response(agent: dict[str, Any]) -> GroupAgentResponse:
    return GroupAgentResponse(
        agent_id=str(agent["_id"]),
        group_id=str(agent["group_id"]),
        template_id=agent["template_id"],
        name=agent["name"],
        description=agent["description"],
        system_prompt=agent["system_prompt"],
        model=agent["model"],
        temperature=agent["temperature"],
        capabilities=agent["capabilities"],
        configuration=agent.get("configuration", {}),
        enabled=agent["enabled"],
        created_by=str(agent["created_by"]),
        created_at=agent["created_at"],
        updated_at=agent["updated_at"],
    )


def _require_agent_id(agent_id: str) -> ObjectId:
    if not valid_object_id(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return ObjectId(agent_id)


@templates_router.get(
    "/templates",
    response_model=list[AgentTemplate],
    summary="List reusable agent templates",
)
async def list_agent_templates(
    request: Request,
    _current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> list[AgentTemplate]:
    return [
        AgentTemplate(**template)
        for template in get_agent_templates(
            request.app.state.settings.default_llm_model
        )
    ]


@group_agents_router.post(
    "/{group_id}/agents",
    response_model=GroupAgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a group agent from a template",
)
async def create_agent(
    group_id: str,
    payload: CreateGroupAgent,
    request: Request,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> GroupAgentResponse:
    group, _ = await _require_group_role(
        database,
        group_id=group_id,
        user_id=current_user.id,
        admin=True,
    )
    template = get_agent_template(
        payload.template_id,
        request.app.state.settings.default_llm_model,
    )
    if template is None:
        raise HTTPException(status_code=404, detail="Agent template not found")

    configuration = (
        payload.configuration.model_dump(exclude_unset=True)
        if payload.configuration is not None
        else {}
    )
    try:
        agent = await create_group_agent(
            database,
            group_id=group["_id"],
            template_id=payload.template_id,
            name=payload.name or template["name"],
            description=template["description"],
            system_prompt=payload.custom_system_prompt or template["system_prompt"],
            model=payload.model or template["model"],
            temperature=(
                payload.temperature
                if payload.temperature is not None
                else template["temperature"]
            ),
            capabilities=payload.capabilities or template["capabilities"],
            configuration=configuration,
            created_by=ObjectId(current_user.id),
        )
    except DuplicateGroupAgentError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This group already has an active agent from that template",
        ) from None

    await sync_group_agent_summary(
        database,
        group_id=group["_id"],
        agent_id=agent["_id"],
        enabled=True,
    )
    return _agent_response(agent)


@group_agents_router.get(
    "/{group_id}/agents",
    response_model=GroupAgentListResponse,
    summary="List agents in a group",
)
async def list_agents(
    group_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> GroupAgentListResponse:
    group, _ = await _require_group_role(
        database,
        group_id=group_id,
        user_id=current_user.id,
    )
    agents = await list_group_agents(database, group["_id"])
    return GroupAgentListResponse(items=[_agent_response(agent) for agent in agents])


@group_agents_router.get(
    "/{group_id}/agents/{agent_id}",
    response_model=GroupAgentResponse,
    summary="Get group agent details",
)
async def get_agent_details(
    group_id: str,
    agent_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> GroupAgentResponse:
    group, _ = await _require_group_role(
        database,
        group_id=group_id,
        user_id=current_user.id,
    )
    agent = await get_group_agent(
        database,
        group_id=group["_id"],
        agent_id=agent_id,
    )
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return _agent_response(agent)


@group_agents_router.put(
    "/{group_id}/agents/{agent_id}",
    response_model=GroupAgentResponse,
    summary="Update a group agent",
)
async def update_agent(
    group_id: str,
    agent_id: str,
    payload: UpdateGroupAgent,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> GroupAgentResponse:
    group, _ = await _require_group_role(
        database,
        group_id=group_id,
        user_id=current_user.id,
        admin=True,
    )
    identifier = _require_agent_id(agent_id)
    if await get_group_agent(
        database,
        group_id=group["_id"],
        agent_id=agent_id,
    ) is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    changes = payload.model_dump(exclude_unset=True)
    if "configuration" in changes:
        config = payload.configuration
        changes["configuration"] = (
            config.model_dump(exclude_unset=True) if config is not None else {}
        )
    updated = await update_group_agent(
        database,
        group_id=group["_id"],
        agent_id=identifier,
        changes=changes,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if "enabled" in changes:
        await sync_group_agent_summary(
            database,
            group_id=group["_id"],
            agent_id=identifier,
            enabled=updated["enabled"],
        )
    return _agent_response(updated)


@group_agents_router.patch(
    "/{group_id}/agents/{agent_id}/status",
    response_model=GroupAgentResponse,
    summary="Enable or disable a group agent",
)
async def update_agent_status(
    group_id: str,
    agent_id: str,
    payload: AgentStatusUpdate,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> GroupAgentResponse:
    group, _ = await _require_group_role(
        database,
        group_id=group_id,
        user_id=current_user.id,
        admin=True,
    )
    identifier = _require_agent_id(agent_id)
    updated = await set_group_agent_enabled(
        database,
        group_id=group["_id"],
        agent_id=identifier,
        enabled=payload.enabled,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    await sync_group_agent_summary(
        database,
        group_id=group["_id"],
        agent_id=identifier,
        enabled=payload.enabled,
    )
    return _agent_response(updated)


@group_agents_router.delete(
    "/{group_id}/agents/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a group agent",
)
async def delete_agent(
    group_id: str,
    agent_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    database: Annotated[Database[dict[str, Any]], Depends(get_database)],
) -> None:
    group, _ = await _require_group_role(
        database,
        group_id=group_id,
        user_id=current_user.id,
        admin=True,
    )
    identifier = _require_agent_id(agent_id)
    deleted = await soft_delete_group_agent(
        database,
        group_id=group["_id"],
        agent_id=identifier,
    )
    if deleted is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    await sync_group_agent_summary(
        database,
        group_id=group["_id"],
        agent_id=identifier,
        enabled=False,
    )
