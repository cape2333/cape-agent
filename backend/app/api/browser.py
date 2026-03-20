import logging
from fastapi import APIRouter
from pydantic import BaseModel

from app.services.browser_service import browser_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/browser")


class ConnectResponse(BaseModel):
    success: bool
    message: str
    tool_count: int = 0


class StatusResponse(BaseModel):
    connected: bool


@router.post("/connect", response_model=ConnectResponse)
async def connect_browser():
    """Launch a stealth browser instance."""
    try:
        await browser_service.connect()
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
    """Close the browser."""
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
