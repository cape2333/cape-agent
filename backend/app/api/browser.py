import logging
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from app.services.browser_service import browser_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/browser")


class ConnectRequest(BaseModel):
    cdp_url: str


class ConnectResponse(BaseModel):
    success: bool
    message: str
    tool_count: int = 0


class StatusResponse(BaseModel):
    connected: bool
    cdp_url: Optional[str] = None


@router.post("/connect", response_model=ConnectResponse)
async def connect_browser(req: ConnectRequest):
    """Connect to browser via CDP URL."""
    try:
        await browser_service.connect(req.cdp_url)
        tools = browser_service.get_tools()
        return ConnectResponse(
            success=True,
            message=f"Connected with {len(tools)} browser tools available",
            tool_count=len(tools),
        )
    except Exception as e:
        logger.error(f"Browser connect error: {e}", exc_info=True)
        return ConnectResponse(
            success=False,
            message=str(e),
        )


@router.post("/disconnect")
async def disconnect_browser():
    """Disconnect from browser."""
    import traceback
    print(f"[BROWSER] Disconnect called (was_connected={browser_service.connected})", flush=True)
    print(f"[BROWSER] Disconnect caller stack:\n{''.join(traceback.format_stack()[-3:])}", flush=True)
    try:
        await browser_service.disconnect()
        return {"success": True, "message": "Disconnected"}
    except Exception as e:
        logger.error(f"Browser disconnect error: {e}", exc_info=True)
        return {"success": False, "message": str(e)}


@router.get("/status", response_model=StatusResponse)
async def browser_status():
    """Get current browser connection status."""
    status = browser_service.get_status()
    return StatusResponse(**status)
