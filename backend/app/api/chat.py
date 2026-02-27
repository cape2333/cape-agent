import json
import logging
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
import aiosqlite

logger = logging.getLogger(__name__)

from app.models.database import get_db
from app.models.schemas import ChatRequest
from app.services.conversation_service import get_messages, add_message
from app.services.agent_service import build_agent, stream_chat

router = APIRouter(prefix="/api")


@router.post("/chat")
async def chat(req: ChatRequest, db: aiosqlite.Connection = Depends(get_db)):
    # Save user message
    await add_message(db, req.conversation_id, "user", req.message)

    # Load conversation history (excluding the message we just added — it'll be the user prompt)
    messages = await get_messages(db, req.conversation_id)
    history = [{"role": m.role, "content": m.content} for m in messages[:-1]]

    print(f"[CHAT] provider={req.provider}, model={req.model}, api_base={req.api_base!r}, api_key={'***' + req.api_key[-4:] if req.api_key and len(req.api_key) > 4 else '(empty)'}", flush=True)

    agent = build_agent(
        provider=req.provider or "openai",
        model_name=req.model or "gpt-4o-mini",
        api_key=req.api_key,
        api_base=req.api_base,
        history=history,
    )

    async def event_stream():
        full_content = ""
        try:
            async for delta in stream_chat(agent, req.message):
                full_content += delta
                yield f"data: {json.dumps({'type': 'delta', 'content': delta})}\n\n"
        except Exception as e:
            logger.error(f"Chat error: {e}", exc_info=True)
            error_msg = str(e)
            if "<html>" in error_msg.lower():
                error_msg = "Failed to reach LLM API. Check your API Base URL and network settings."
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg})}\n\n"
            return

        # Save assistant message
        await add_message(db, req.conversation_id, "assistant", full_content)
        yield f"data: {json.dumps({'type': 'done', 'content': full_content})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
