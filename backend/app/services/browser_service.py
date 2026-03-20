import logging
import os
import signal
import time
from pathlib import Path
from typing import List

from camel.toolkits import FunctionTool

logger = logging.getLogger(__name__)


class BrowserService:
    """Manages HybridBrowserToolkit with its own stealth browser instance."""

    def __init__(self):
        self._toolkit = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    @staticmethod
    def _kill_stale_chromium(profile_dir: str) -> None:
        """Kill any orphaned Chromium process using our profile directory."""
        lock_path = os.path.join(profile_dir, "SingletonLock")
        if not os.path.islink(lock_path) and not os.path.exists(lock_path):
            return

        # SingletonLock is a symlink whose target encodes "hostname-PID"
        try:
            target = os.readlink(lock_path)
            pid_str = target.rsplit("-", 1)[-1]
            pid = int(pid_str)
        except (OSError, ValueError, IndexError):
            # Broken/unreadable link – just remove it
            try:
                os.remove(lock_path)
                logger.info(f"Removed broken SingletonLock: {lock_path}")
            except OSError:
                pass
            return

        # Check if process is alive
        try:
            os.kill(pid, 0)
        except OSError:
            # Process dead – remove stale lock
            try:
                os.remove(lock_path)
                logger.info(
                    f"Removed stale SingletonLock (PID {pid} dead): {lock_path}"
                )
            except OSError:
                pass
            return

        # Process is alive – kill the orphaned Chromium
        logger.info(f"Killing orphaned Chromium process {pid}")
        try:
            os.kill(pid, signal.SIGTERM)
            # Wait up to 3 seconds for graceful exit
            for _ in range(30):
                time.sleep(0.1)
                try:
                    os.kill(pid, 0)
                except OSError:
                    break  # Process exited
            else:
                # Still alive after 3s – force kill
                logger.warning(f"Force-killing Chromium process {pid}")
                os.kill(pid, signal.SIGKILL)
                time.sleep(0.5)
        except OSError:
            pass  # Process already gone

        # Remove lock file
        try:
            os.remove(lock_path)
            logger.info(f"Removed SingletonLock after killing PID {pid}")
        except OSError:
            pass

    async def connect(self) -> None:
        """Launch a stealth browser via HybridBrowserToolkit."""
        from camel.toolkits import HybridBrowserToolkit

        if self._connected:
            await self.disconnect()

        # Persistent profile so cookies/history survive across sessions
        profile_dir = os.path.join(
            str(Path.home()), ".cape-agent", "browser_profiles", "default"
        )
        os.makedirs(profile_dir, exist_ok=True)

        # Kill any orphaned Chromium from previous crashed sessions
        self._kill_stale_chromium(profile_dir)

        logger.info(
            f"Launching stealth browser (profile: {profile_dir})"
        )

        self._toolkit = HybridBrowserToolkit(
            headless=False,
            stealth=True,
            user_data_dir=profile_dir,
        )

        # Eagerly initialize so tools are available immediately
        await self._toolkit._ensure_ws_wrapper()

        tools = self._toolkit.get_tools()
        self._connected = True
        logger.info(f"Browser service ready, {len(tools)} tools available")

    async def disconnect(self) -> None:
        """Close the browser and clean up."""
        if self._toolkit:
            try:
                # browser_close() does full cleanup: pages, context, browser
                # process — unlike disconnect_websocket() which may leave
                # the Chromium process alive.
                await self._toolkit.browser_close()
            except Exception as e:
                logger.warning(f"browser_close failed: {e}")
                # Fallback: try disconnect_websocket
                try:
                    await self._toolkit.disconnect_websocket()
                except Exception as e2:
                    logger.warning(f"disconnect_websocket also failed: {e2}")
            self._toolkit = None
        self._connected = False
        logger.info("Browser service disconnected")

    def get_tools(self) -> List[FunctionTool]:
        """Return the browser tools for ChatAgent."""
        if not self._toolkit:
            return []
        return self._toolkit.get_tools()

    def get_status(self) -> dict:
        return {
            "connected": self._connected,
        }


# Singleton instance
browser_service = BrowserService()
