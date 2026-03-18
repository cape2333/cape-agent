# backend/app/api/chat.py
import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
import aiosqlite

from app.models.database import get_db
from app.models.enums import Status
from app.models.schemas import ChatRequest, sse_json
from app.services.conversation_service import (
    get_messages,
    add_message,
    conversation_exists,
    get_conversation,
)
from app.services.agent_service import build_agent, agent_chat, build_workforce
from app.services.task_lock import TaskLock
from app.agents.factory import create_classifier_agent, classify_question
from app.services.agent_service import build_model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.post("/chat")
async def chat(req: ChatRequest, db: aiosqlite.Connection = Depends(get_db)):
    if not await conversation_exists(db, req.conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")

    try:
        await add_message(db, req.conversation_id, "user", req.message)
    except aiosqlite.IntegrityError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc

    messages = await get_messages(db, req.conversation_id)
    history = [{"role": m.role, "content": m.content} for m in messages[:-1]]

    provider = req.provider or "openai"
    model_name = req.model or "gpt-4o-mini"

    logger.info(f"[CHAT] provider={provider}, model={model_name}")

    async def event_stream():
        task_lock = TaskLock(
            id=req.conversation_id,
            status=Status.classifying,
        )

        try:
            # Classify question
            model = build_model(provider, model_name, req.api_key, req.api_base)
            classifier = create_classifier_agent(model)
            classification = await classify_question(
                classifier, req.message, history
            )
            logger.info(f"[CHAT] classification={classification}")

            if classification == "simple":
                # Simple path: direct streaming
                agent = build_agent(
                    provider=provider,
                    model_name=model_name,
                    api_key=req.api_key,
                    api_base=req.api_base,
                    history=history,
                )
                full_content = ""
                async for event in agent_chat(agent, req.message):
                    if event["type"] == "delta":
                        yield sse_json("delta", {"content": event["content"]})
                        full_content += event["content"]
                    elif event["type"] == "done":
                        full_content = event.get("content", full_content)

                await add_message(
                    db, req.conversation_id, "assistant", full_content
                )
                conv = await get_conversation(db, req.conversation_id)
                yield sse_json("done", {
                    "content": full_content,
                    "conversation": conv.model_dump() if conv else None,
                })

            else:
                # Complex path: workforce
                workforce = build_workforce(
                    task_lock=task_lock,
                    provider=provider,
                    model_name=model_name,
                    api_key=req.api_key,
                    api_base=req.api_base,
                )

                bg_task = asyncio.create_task(workforce.run(req.message))
                task_lock.background_tasks.add(bg_task)

                while True:
                    if bg_task.done() and task_lock.queue.empty():
                        exc = bg_task.exception()
                        if exc:
                            yield sse_json("error", {"message": str(exc)})
                        break

                    try:
                        event = await asyncio.wait_for(
                            task_lock.get_event(), timeout=300
                        )
                    except asyncio.TimeoutError:
                        yield sse_json("error", {
                            "message": "Workforce timed out"
                        })
                        break

                    if event["step"] == "end":
                        content = event["data"].get("content", "")
                        await add_message(
                            db, req.conversation_id, "assistant", content
                        )
                        conv = await get_conversation(db, req.conversation_id)
                        yield sse_json("end", {
                            "content": content,
                            "conversation": conv.model_dump() if conv else None,
                        })
                        break
                    elif event["step"] == "error":
                        yield sse_json("error", event["data"])
                        break
                    else:
                        yield sse_json(event["step"], event["data"])

                if not bg_task.done():
                    bg_task.cancel()
                    try:
                        await bg_task
                    except asyncio.CancelledError:
                        pass

        except Exception as e:
            logger.error(f"Chat error: {e}", exc_info=True)
            error_msg = str(e)
            if "API" in error_msg and "key" in error_msg.lower():
                error_msg = "API key is missing. Please configure it in Settings."
            yield sse_json("error", {"message": error_msg})
        finally:
            await task_lock.cleanup()

    return StreamingResponse(event_stream(), media_type="text/event-stream")
