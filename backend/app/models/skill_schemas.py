from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class SkillMeta(BaseModel):
    name: str
    description: str
    agent_type: Literal["browser", "developer", "document"]
    version: int = 1
    enabled: bool = True
    created_by: Literal["agent", "user"] = "user"
    created_at: str = ""
    updated_at: str = ""
    tags: list[str] = Field(default_factory=list)


class SkillDetail(SkillMeta):
    content: str = ""
    raw: str = ""
    files: list[str] = Field(default_factory=list)


class SkillCreate(BaseModel):
    name: str
    description: str
    agent_type: Literal["browser", "developer", "document"]
    content: str
    tags: list[str] = Field(default_factory=list)


class SkillUpdate(BaseModel):
    description: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    enabled: Optional[bool] = None


class SkillStats(BaseModel):
    name: str
    loads: int = 0
    patches: int = 0
    last_used: Optional[str] = None


class SkillLogEntry(BaseModel):
    event: str
    skill: str
    agent_type: str
    conversation_id: Optional[str] = None
    timestamp: str


class InsightRecord(BaseModel):
    agent_type: Literal["browser", "developer", "document"]
    summary: str
    context: str = ""
    conversation_id: str = ""
    timestamp: str = ""
