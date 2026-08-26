from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import agents
import agents_store
from auth_routes import current_user

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentRequest(BaseModel):
    name: str
    kind: str
    config: dict
    description: str = ""
    trigger: str = "manual"
    interval_s: int = 0
    enabled: bool = True
    agent_id: Optional[str] = None


class RunAgentRequest(BaseModel):
    input: str = ""


class EnableRequest(BaseModel):
    enabled: bool


class ProbeRequest(BaseModel):
    url: str


@router.get("/status")
def agents_status(user: dict = Depends(current_user)):
    return agents.status()


@router.get("")
def agents_list(user: dict = Depends(current_user)):
    return {"agents": agents_store.list_agents(user["user_id"])}


@router.get("/{agent_id}")
def agents_get(agent_id: str, user: dict = Depends(current_user)):
    try:
        return agents_store.get_agent(user["user_id"], agent_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("")
def agents_save(req: AgentRequest, user: dict = Depends(current_user)):
    try:
        config = agents.validate(req.name, req.kind, req.config, req.trigger, req.interval_s)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        return agents_store.save_agent(
            owner_id=user["user_id"],
            name=req.name.strip()[:120],
            kind=req.kind,
            config=config,
            description=req.description.strip()[:500],
            trigger=req.trigger,
            interval_s=req.interval_s,
            enabled=req.enabled,
            agent_id=req.agent_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{agent_id}")
def agents_enable(agent_id: str, req: EnableRequest, user: dict = Depends(current_user)):
    try:
        return agents_store.set_enabled(user["user_id"], agent_id, req.enabled)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{agent_id}")
def agents_delete(agent_id: str, user: dict = Depends(current_user)):
    try:
        agents_store.delete_agent(user["user_id"], agent_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"deleted": True}


@router.post("/{agent_id}/run")
def agents_run(agent_id: str, req: RunAgentRequest, user: dict = Depends(current_user)):
    try:
        agent = agents_store.get_agent(user["user_id"], agent_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        return agents.run_agent(agent, user, req.input, agents.TRIGGER_MANUAL)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc))


@router.get("/{agent_id}/runs")
def agents_runs(agent_id: str, limit: int = 25, user: dict = Depends(current_user)):
    try:
        agents_store.get_agent(user["user_id"], agent_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"runs": agents_store.list_runs(user["user_id"], agent_id, min(limit, 100))}


@router.get("/runs/{run_id}")
def agents_run_detail(run_id: str, user: dict = Depends(current_user)):
    try:
        return agents_store.get_run(user["user_id"], run_id)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/probe")
def agents_probe(req: ProbeRequest, user: dict = Depends(current_user)):
    allowed, reason = agents.external_target_allowed(req.url)
    return {"allowed": allowed, "reason": reason}
