from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.models.skill_schemas import (
    SkillCreate,
    SkillDetail,
    SkillMeta,
    SkillStats,
    SkillUpdate,
)
from app.services.skill_service import skill_service
from app.services.skill_logger import skill_logger
from app.services.skill_hygiene import run_hygiene, HygieneReport

router = APIRouter(prefix="/api/skills", tags=["skills"])


def _update_error_status(msg: str) -> int:
    return 404 if "not found" in msg.lower() else 400


@router.get("", response_model=list[SkillMeta])
async def list_skills(
    agent_type: Optional[str] = Query(None),
    enabled: Optional[bool] = Query(None),
    tag: Optional[str] = Query(None),
):
    return skill_service.list_skills(agent_type=agent_type, enabled=enabled, tag=tag)


@router.get("/stats")
async def get_stats() -> dict[str, dict]:
    raw = skill_logger.get_stats()
    out: dict[str, dict] = {}
    for name, data in raw.items():
        utility = skill_logger.compute_utility(data)
        recent_utility = skill_logger.compute_recent_utility(data, days=30)
        stats = SkillStats(
            name=name,
            **{k: v for k, v in data.items() if k in SkillStats.model_fields},
        )
        stats.utility = utility
        stats.recent_utility_30d = recent_utility
        out[name] = stats.model_dump()
    return out


@router.post("/hygiene", response_model=HygieneReport)
async def trigger_hygiene() -> HygieneReport:
    """Run library hygiene: archive low-utility skills, dedup, enforce caps.

    Idempotent and safe to call repeatedly. All actions are soft —
    archived skills can be re-enabled from the UI.
    """
    return run_hygiene()


@router.get("/logs")
async def get_logs(limit: int = Query(50), skill: Optional[str] = Query(None)):
    import json
    from datetime import datetime, timezone

    entries = []
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    events_file = skill_logger.log_dir / month / "events.jsonl"
    if events_file.exists():
        for line in events_file.read_text(encoding="utf-8").strip().split("\n"):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if skill and entry.get("skill") != skill:
                continue
            entries.append(entry)
    return entries[-limit:]


@router.get("/{name}", response_model=SkillDetail)
async def get_skill(name: str):
    detail = skill_service.get_skill(name)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return detail


@router.post("", response_model=SkillMeta, status_code=201)
async def create_skill(req: SkillCreate):
    try:
        return skill_service.create_skill(
            name=req.name,
            description=req.description,
            agent_type=req.agent_type,
            content=req.content,
            tags=req.tags,
            created_by="user",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{name}", response_model=SkillMeta)
async def update_skill_partial(name: str, req: SkillUpdate):
    try:
        return skill_service.update_skill(
            name,
            description=req.description,
            content=req.content,
            tags=req.tags,
            enabled=req.enabled,
        )
    except ValueError as e:
        msg = str(e)
        raise HTTPException(status_code=_update_error_status(msg), detail=msg)


@router.delete("/{name}")
async def delete_skill(name: str):
    try:
        skill_service.delete_skill(name)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{name}/files")
async def list_skill_files(name: str):
    detail = skill_service.get_skill(name)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    return detail.files


@router.get("/{name}/files/{file_path:path}")
async def read_skill_file(name: str, file_path: str):
    if not skill_service.find_skill_dir(name):
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    target = skill_service.resolve_skill_file(name, file_path)
    if target is None:
        raise HTTPException(status_code=400, detail=f"Invalid file path '{file_path}'")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"File '{file_path}' not found")
    return {"content": target.read_text(encoding="utf-8")}


@router.put("/{name}/files/{file_path:path}")
async def write_skill_file(name: str, file_path: str, body: dict):
    if not skill_service.find_skill_dir(name):
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    target = skill_service.resolve_skill_file(name, file_path)
    if target is None:
        raise HTTPException(status_code=400, detail=f"Invalid file path '{file_path}'")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.get("content", ""), encoding="utf-8")
    return {"ok": True}


@router.delete("/{name}/files/{file_path:path}")
async def delete_skill_file(name: str, file_path: str):
    if not skill_service.find_skill_dir(name):
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    target = skill_service.resolve_skill_file(name, file_path)
    if target is None:
        raise HTTPException(status_code=400, detail=f"Invalid file path '{file_path}'")
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"File '{file_path}' not found")
    target.unlink()
    return {"ok": True}
