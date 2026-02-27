from fastapi import APIRouter, Depends, HTTPException
import aiosqlite

from app.models.database import get_db
from app.models.schemas import ConversationCreate
from app.services.conversation_service import (
    list_conversations, create_conversation, delete_conversation, get_messages,
)

router = APIRouter(prefix="/api")


@router.get("/conversations")
async def get_conversations(db: aiosqlite.Connection = Depends(get_db)):
    return await list_conversations(db)


@router.post("/conversations")
async def post_conversation(
    body: ConversationCreate = ConversationCreate(),
    db: aiosqlite.Connection = Depends(get_db),
):
    return await create_conversation(db, body.title or "New Chat")


@router.delete("/conversations/{conversation_id}")
async def remove_conversation(
    conversation_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    ok = await delete_conversation(db, conversation_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True}


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    db: aiosqlite.Connection = Depends(get_db),
):
    return await get_messages(db, conversation_id)
