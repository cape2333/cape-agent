import logging
from typing import Optional, List

from camel.toolkits import FunctionTool

logger = logging.getLogger(__name__)


class BrowserService:
    """Manages HybridBrowserToolkit instance and CDP connection."""

    def __init__(self):
        self._toolkit = None
        self._cdp_url: Optional[str] = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def cdp_url(self) -> Optional[str]:
        return self._cdp_url

    async def connect(self, cdp_url: str) -> None:
        """Connect to the Electron browser panel via CDP."""
        from camel.toolkits import HybridBrowserToolkit

        if self._connected:
            await self.disconnect()

        logger.info(f"Connecting to CDP: {cdp_url}")
        self._cdp_url = cdp_url

        self._toolkit = HybridBrowserToolkit(
            headless=False,
            connect_over_cdp=True,
            cdp_url=cdp_url,
            cdp_keep_current_page=True,
        )

        # Eagerly initialize the WebSocket connection to verify it works
        await self._toolkit._ensure_ws_wrapper()

        tools = self._toolkit.get_tools()
        self._connected = True
        logger.info(f"Browser service connected successfully, {len(tools)} tools available")

    async def disconnect(self) -> None:
        """Disconnect from the browser (don't close it)."""
        if self._toolkit:
            try:
                await self._toolkit.disconnect_websocket()
            except Exception as e:
                logger.warning(f"Error closing toolkit: {e}")
            self._toolkit = None
        self._connected = False
        self._cdp_url = None
        logger.info("Browser service disconnected")

    def get_tools(self) -> List[FunctionTool]:
        """Return the browser tools for ChatAgent."""
        if not self._toolkit:
            return []
        return self._toolkit.get_tools()

    def get_status(self) -> dict:
        return {
            "connected": self._connected,
            "cdp_url": self._cdp_url,
        }


# Singleton instance
browser_service = BrowserService()
