import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import aiosqlite

logger = logging.getLogger(__name__)

from app.models.database import get_db
from app.models.schemas import ChatRequest
from app.services.conversation_service import (
    get_messages,
    add_message,
    conversation_exists,
    get_conversation,
)
from app.services.agent_service import build_agent, agent_chat
from app.services.browser_service import browser_service

router = APIRouter(prefix="/api")


@router.post("/chat")
async def chat(req: ChatRequest, db: aiosqlite.Connection = Depends(get_db)):
    if not await conversation_exists(db, req.conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Save user message
    try:
        await add_message(db, req.conversation_id, "user", req.message)
    except aiosqlite.IntegrityError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    current_conversation = await get_conversation(db, req.conversation_id)

    # Load conversation history (excluding the message we just added — it'll be the user prompt)
    messages = await get_messages(db, req.conversation_id)
    history = [{"role": m.role, "content": m.content} for m in messages[:-1]]

    print(f"[CHAT] provider={req.provider}, model={req.model}, api_base={req.api_base!r}, api_key={'***' + req.api_key[-4:] if req.api_key and len(req.api_key) > 4 else '(empty)'}", flush=True)

    # Get browser tools if connected
    tools = browser_service.get_tools() if browser_service.connected else []
    if tools:
        tool_names = [t.get_function_name() for t in tools]
        print(f"[CHAT] Browser connected, {len(tools)} tools: {tool_names}", flush=True)
    else:
        print(f"[CHAT] No browser tools (connected={browser_service.connected})", flush=True)

    try:
        agent = build_agent(
            provider=req.provider or "openai",
            model_name=req.model or "gpt-4o-mini",
            api_key=req.api_key,
            api_base=req.api_base,
            history=history,
            tools=tools,
        )
    except Exception as e:
        logger.error(f"Agent build error: {e}", exc_info=True)
        error_msg = str(e)
        if "API" in error_msg and "key" in error_msg.lower():
            error_msg = "API key is missing. Please configure it in Settings."
        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg, 'conversation': current_conversation.model_dump() if current_conversation else None})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    async def event_stream():
        full_content = ""
        try:
            async for event in agent_chat(agent, req.message):
                event_type = event.get("type")

                if event_type == "delta":
                    full_content += event["content"]
                    yield f"data: {json.dumps({'type': 'delta', 'content': event['content']})}\n\n"

                elif event_type == "tool_start":
                    yield f"data: {json.dumps({'type': 'tool_start', 'step_id': event.get('step_id', ''), 'tool_name': event.get('tool_name', ''), 'tool_args': event.get('tool_args', {})})}\n\n"

                elif event_type == "tool_result":
                    yield f"data: {json.dumps({'type': 'tool_result', 'step_id': event.get('step_id', ''), 'tool_name': event.get('tool_name', ''), 'tool_result': event.get('tool_result', '')})}\n\n"

                elif event_type == "done":
                    full_content = event.get("content", full_content)

        except Exception as e:
            logger.error(f"Chat error: {e}", exc_info=True)
            error_msg = str(e)
            if "<html>" in error_msg.lower():
                error_msg = "Failed to reach LLM API. Check your API Base URL and network settings."
            yield f"data: {json.dumps({'type': 'error', 'content': error_msg, 'conversation': current_conversation.model_dump() if current_conversation else None})}\n\n"
            return

        # Save assistant message
        await add_message(db, req.conversation_id, "assistant", full_content)
        updated_conversation = await get_conversation(db, req.conversation_id)
        yield f"data: {json.dumps({'type': 'done', 'content': full_content, 'conversation': updated_conversation.model_dump() if updated_conversation else None})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
