import aiosqlite
from typing import List
from app.models.schemas import (
    ConversationResponse, MessageResponse, gen_id, now_iso,
)


async def list_conversations(db: aiosqlite.Connection) -> List[ConversationResponse]:
    cursor = await db.execute(
        "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
    )
    rows = await cursor.fetchall()
    return [
        ConversationResponse(id=r[0], title=r[1], created_at=r[2], updated_at=r[3])
        for r in rows
    ]


async def create_conversation(db: aiosqlite.Connection, title: str = "New Chat") -> ConversationResponse:
    cid = gen_id()
    ts = now_iso()
    await db.execute(
        "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (cid, title, ts, ts),
    )
    await db.commit()
    return ConversationResponse(id=cid, title=title, created_at=ts, updated_at=ts)


async def get_conversation(
    db: aiosqlite.Connection,
    conversation_id: str,
) -> ConversationResponse | None:
    cursor = await db.execute(
        "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
        (conversation_id,),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return ConversationResponse(id=row[0], title=row[1], created_at=row[2], updated_at=row[3])


async def conversation_exists(db: aiosqlite.Connection, conversation_id: str) -> bool:
    cursor = await db.execute(
        "SELECT 1 FROM conversations WHERE id = ? LIMIT 1",
        (conversation_id,),
    )
    return await cursor.fetchone() is not None


async def delete_conversation(db: aiosqlite.Connection, conversation_id: str) -> bool:
    await db.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    cursor = await db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    await db.commit()
    return cursor.rowcount > 0


async def get_messages(db: aiosqlite.Connection, conversation_id: str) -> List[MessageResponse]:
    cursor = await db.execute(
        "SELECT id, conversation_id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
        (conversation_id,),
    )
    rows = await cursor.fetchall()
    return [
        MessageResponse(id=r[0], conversation_id=r[1], role=r[2], content=r[3], created_at=r[4])
        for r in rows
    ]


async def add_message(db: aiosqlite.Connection, conversation_id: str, role: str, content: str) -> MessageResponse:
    mid = gen_id()
    ts = now_iso()
    await db.execute(
        "INSERT INTO messages (id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (mid, conversation_id, role, content, ts),
    )
    # Update conversation timestamp and title if first message
    cursor = await db.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,)
    )
    count = (await cursor.fetchone())[0]
    if count == 1 and role == "user":
        title = content[:50] + ("..." if len(content) > 50 else "")
        await db.execute(
            "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
            (title, ts, conversation_id),
        )
    else:
        await db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (ts, conversation_id),
        )
    await db.commit()
    return MessageResponse(id=mid, conversation_id=conversation_id, role=role, content=content, created_at=ts)
