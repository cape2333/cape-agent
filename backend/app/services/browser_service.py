import logging
import os
from pathlib import Path
from typing import List

import psutil
from camel.toolkits import FunctionTool

logger = logging.getLogger(__name__)


def _ws_is_dead(ws_wrapper) -> bool:
    """Check if a WebSocket wrapper's connection is dead."""
    if ws_wrapper is None:
        return False  # No wrapper = nothing to check
    if ws_wrapper.websocket is None:
        return True
    # Also check websockets library state if available
    try:
        import websockets.protocol
        if ws_wrapper.websocket.state != websockets.protocol.State.OPEN:
            return True
    except (ImportError, AttributeError):
        pass
    return False


def _browser_process_dead(ws_wrapper) -> bool:
    """Check if the Node.js driver subprocess behind the WS has exited.

    The driver launches Chromium and pipes CDP over WebSocket. If the
    driver exits, the WS is effectively useless even if reconnection
    would succeed at the socket layer.
    """
    if ws_wrapper is None:
        return False
    proc = getattr(ws_wrapper, "process", None)
    if proc is None:
        return False
    return proc.poll() is not None


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
        """Kill every process still holding the browser profile, then drop
        the SingletonLock file.

        Chromium's ``SingletonLock`` only points at the main browser PID,
        but a live Chromium session also spawns many helper processes
        (renderer, GPU, utility). Killing only the main PID leaves
        helpers anchored to the profile dir, so the next launch still
        fails with ``SingletonLock: File exists``. We instead enumerate
        every process whose cmdline references our profile and terminate
        the lot before clearing the lock file.
        """
        profile_dir = os.path.abspath(profile_dir)
        needle = f"--user-data-dir={profile_dir}"

        victims: list[psutil.Process] = []
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = proc.info.get("cmdline") or []
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            # Match either the exact flag form or any arg containing the
            # profile path (covers ``--user-data-dir=<path>`` and
            # ``--user-data-dir <path>`` and helper-process variants).
            if any(needle in arg or profile_dir in arg for arg in cmdline):
                victims.append(psutil.Process(proc.info["pid"]))

        if victims:
            logger.info(
                "Killing %d stale process(es) holding profile %s: pids=%s",
                len(victims),
                profile_dir,
                [p.pid for p in victims],
            )
            for p in victims:
                try:
                    p.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            gone, alive = psutil.wait_procs(victims, timeout=3)
            for p in alive:
                logger.warning("Force-killing stubborn PID %s", p.pid)
                try:
                    p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            psutil.wait_procs(alive, timeout=2)

        # Always clear lock files once processes are gone. macOS Chromium
        # can leave SingletonLock / SingletonSocket / SingletonCookie
        # behind after a crash — each blocks the next launch.
        for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            path = os.path.join(profile_dir, name)
            if os.path.islink(path) or os.path.exists(path):
                try:
                    os.remove(path)
                    logger.info("Removed stale %s: %s", name, path)
                except OSError as e:
                    logger.warning("Could not remove %s: %s", path, e)

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

        # Patch _ensure_ws_wrapper to auto-reconnect dead WebSockets.
        # CAMEL's original only creates a wrapper when _ws_wrapper is None,
        # but after a disconnect the wrapper object persists with a dead
        # websocket — so reconnection never happens. Our patch detects this
        # and cleans up before letting the original recreate the connection.
        _original_ensure_ws = self._toolkit._ensure_ws_wrapper

        async def _ensure_ws_with_reconnect():
            ws = self._toolkit._ws_wrapper
            proc_dead = _browser_process_dead(ws)
            if proc_dead:
                # Driver subprocess exited — the browser is gone. A
                # simple WS reconnect can't recover this; mark the
                # service disconnected so callers can trigger a full
                # connect() which relaunches Chromium and cleans the
                # stale profile lock.
                logger.warning(
                    "Browser driver subprocess exited (rc=%s); "
                    "marking service disconnected",
                    ws.process.returncode if ws and ws.process else "?",
                )
                try:
                    await ws.stop()
                except Exception as e:
                    logger.warning(f"Error stopping dead wrapper: {e}")
                self._toolkit._ws_wrapper = None
                self._connected = False
                raise RuntimeError(
                    "Browser driver subprocess exited; call "
                    "browser_service.connect() to relaunch."
                )
            if _ws_is_dead(ws):
                logger.info(
                    "Dead WebSocket detected, reconnecting..."
                )
                try:
                    await ws.stop()
                except Exception as e:
                    logger.warning(f"Error stopping dead wrapper: {e}")
                self._toolkit._ws_wrapper = None
            await _original_ensure_ws()

        self._toolkit._ensure_ws_wrapper = _ensure_ws_with_reconnect

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
