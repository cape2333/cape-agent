import logging
import socket
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.models.database import init_db
from app.api.conversations import router as conversations_router
from app.api.chat import router as chat_router
from app.api.settings import router as settings_router
from app.api.browser import router as browser_router
from app.api.skills import router as skills_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Cape Agent Backend", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(conversations_router)
app.include_router(chat_router)
app.include_router(settings_router)
app.include_router(browser_router)
app.include_router(skills_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


def find_free_port(preferred: int = 8001) -> int:
    """Try the preferred port first; if busy, let the OS pick a free one."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", preferred))
        sock.close()
        return preferred
    except OSError:
        sock.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        return port


def get_port_file() -> Path:
    port_file = os.environ.get("CAPE_AGENT_PORT_FILE")
    if port_file:
        return Path(port_file)
    return Path(__file__).resolve().parent.parent / ".backend_port"


if __name__ == "__main__":
    port = find_free_port(8001)
    port_file = get_port_file()
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text(str(port))
    print(f"Backend starting on port {port}")
    reload_enabled = os.environ.get("CAPE_AGENT_RELOAD") == "1"
    if reload_enabled:
        uvicorn.run("main:app", host="127.0.0.1", port=port, reload=True)
    else:
        uvicorn.run(app, host="127.0.0.1", port=port, reload=False)
