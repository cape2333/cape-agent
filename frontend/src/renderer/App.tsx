import React, { useEffect, useRef, useCallback } from "react";
import { PanelLeftOpen, Search, SquarePen, Globe, X } from "lucide-react";
import Sidebar from "./components/layout/Sidebar";
import ChatArea from "./components/layout/ChatArea";
import InputBar from "./components/layout/InputBar";
import SettingsModal from "./components/settings/SettingsModal";
import { useStore } from "./stores/store";
import { useConversations } from "./hooks/useConversations";
import { initApiUrl, connectBrowser } from "./services/api";

const App: React.FC = () => {
  const sidebarCollapsed = useStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useStore((s) => s.toggleSidebar);
  const theme = useStore((s) => s.settings.theme);
  const browserPanelVisible = useStore((s) => s.browserPanelVisible);
  const setBrowserPanelVisible = useStore((s) => s.setBrowserPanelVisible);
  const setCdpTargetUrl = useStore((s) => s.setCdpTargetUrl);
  const setBrowserCurrentUrl = useStore((s) => s.setBrowserCurrentUrl);
  const browserCurrentUrl = useStore((s) => s.browserCurrentUrl);
  const browserPanelRatio = useStore((s) => s.browserPanelRatio);
  const setBrowserPanelRatio = useStore((s) => s.setBrowserPanelRatio);
  const { createNew } = useConversations();

  // Drag refs — store state captured at drag start to avoid circular dependencies
  const isDragging = useRef(false);
  const dragWindowWidth = useRef(0);
  const dragSidebarWidth = useRef(0);

  const handleCloseBrowser = async () => {
    try {
      await window.electronAPI.browserPanel.hide();
    } catch { /* ignore */ }
    setBrowserPanelVisible(false);
  };

  useEffect(() => {
    initApiUrl();
  }, []);

  // Auto-connect CDP on startup
  useEffect(() => {
    let cancelled = false;

    const autoConnect = async () => {
      await new Promise((r) => setTimeout(r, 2000));
      if (cancelled) return;

      const maxRetries = 3;
      for (let attempt = 1; attempt <= maxRetries; attempt++) {
        if (cancelled) return;
        try {
          const info = await window.electronAPI.browserPanel.getInfo();
          const cdpPort = info.cdpPort || 9222;
          const cdpHttpUrl = `http://127.0.0.1:${cdpPort}`;

          setCdpTargetUrl(cdpHttpUrl);

          const connectResult = await connectBrowser(cdpHttpUrl);
          console.log(`[Auto] Backend CDP connect result (attempt ${attempt}):`, connectResult);

          if (connectResult.success) {
            console.log(`[Auto] Browser connected with ${connectResult.tool_count} tools`);
            break;
          } else {
            console.warn(`[Auto] Connect failed (attempt ${attempt}):`, connectResult.message);
            if (attempt < maxRetries) {
              await new Promise((r) => setTimeout(r, 2000));
            }
          }
        } catch (e) {
          console.error(`[Auto] Failed to auto-connect browser (attempt ${attempt}):`, e);
          if (attempt < maxRetries) {
            await new Promise((r) => setTimeout(r, 2000));
          }
        }
      }
    };

    autoConnect();
    return () => { cancelled = true; };
  }, []);

  // Sync sidebar width and browser panel ratio to main process
  useEffect(() => {
    if (browserPanelVisible) {
      const sw = sidebarCollapsed ? 0 : 268;
      window.electronAPI.browserPanel.resize(sw, browserPanelRatio);
    }
  }, [sidebarCollapsed, browserPanelVisible, browserPanelRatio]);

  // ─── Drag handlers ──────────────────────────────────────────────────────
  // The React app is inside mainView, which only occupies the LEFT portion
  // of the window. So window.innerWidth = mainView width, NOT full window.
  // At drag start, we compute the full window width from the known ratio:
  //   mainViewWidth = W - (W - sw) * ratio = W*(1-ratio) + sw*ratio
  //   W = (mainViewWidth - sw*ratio) / (1-ratio)
  // Then during drag, e.clientX is the position from the left edge of the
  // full window (since mainView.x = 0), so the calculation stays correct.

  const handleDragStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;

    const sw = sidebarCollapsed ? 0 : 268;
    dragSidebarWidth.current = sw;

    const mainViewWidth = window.innerWidth;
    const currentRatio = useStore.getState().browserPanelRatio;

    // Compute full window width from current mainView width and ratio
    if (currentRatio < 0.99) {
      dragWindowWidth.current = (mainViewWidth - sw * currentRatio) / (1 - currentRatio);
    } else {
      dragWindowWidth.current = mainViewWidth * 2;
    }

    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, [sidebarCollapsed]);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return;

      const W = dragWindowWidth.current;
      const sw = dragSidebarWidth.current;
      const contentWidth = W - sw;
      if (contentWidth <= 0) return;

      // e.clientX is relative to the mainView's left edge,
      // which is also the window's left edge (mainView.x = 0)
      const mouseX = e.clientX - sw;
      const newRatio = 1 - (mouseX / contentWidth);
      const clampedRatio = Math.max(0.15, Math.min(0.85, newRatio));
      setBrowserPanelRatio(clampedRatio);
    };

    const handleMouseUp = () => {
      if (isDragging.current) {
        isDragging.current = false;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [setBrowserPanelRatio]);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") {
      root.classList.add("dark");
    } else if (theme === "light") {
      root.classList.remove("dark");
    } else {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      const apply = () => {
        mq.matches ? root.classList.add("dark") : root.classList.remove("dark");
      };
      apply();
      mq.addEventListener("change", apply);
      return () => mq.removeEventListener("change", apply);
    }
  }, [theme]);

  return (
    <div className="flex h-full bg-warm-100 text-warm-800">
      <div
        className="sidebar-transition flex-shrink-0 overflow-hidden"
        style={{ width: sidebarCollapsed ? 0 : 268 }}
      >
        <div className="h-full p-1.5" style={{ width: 268 }}>
          <div className="h-full bg-white rounded-2xl border border-warm-200 shadow-sm overflow-hidden">
            <Sidebar />
          </div>
        </div>
      </div>
      {/* Chat area — fills the mainView; browser is overlaid by Electron main process */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Drag region for macOS title bar */}
        <div
          className="h-12 flex-shrink-0 border-b border-warm-200 flex items-center justify-between"
          style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
        >
          {sidebarCollapsed ? (
            <div
              className="flex items-center gap-1"
              style={{ marginLeft: 80 }}
            >
              <button
                onClick={toggleSidebar}
                className="p-1.5 rounded-lg text-warm-400 hover:text-warm-600 hover:bg-warm-200 transition-colors"
                style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
                title="Open sidebar"
              >
                <PanelLeftOpen size={16} />
              </button>
              <button
                className="p-1.5 rounded-lg text-warm-400 hover:text-warm-600 hover:bg-warm-200 transition-colors"
                style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
                title="Search"
              >
                <Search size={16} />
              </button>
              <button
                onClick={createNew}
                className="p-1.5 rounded-lg text-warm-400 hover:text-warm-600 hover:bg-warm-200 transition-colors"
                style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
                title="New chat"
              >
                <SquarePen size={16} />
              </button>
            </div>
          ) : (
            <div />
          )}
          {browserPanelVisible && (
            <div
              className="flex items-center gap-2 pr-3"
              style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
            >
              <Globe size={14} className="text-accent-500 flex-shrink-0" />
              <span className="text-xs text-warm-400 truncate max-w-[200px]">
                {browserCurrentUrl || "Browser"}
              </span>
              <button
                onClick={handleCloseBrowser}
                className="p-1 rounded-lg text-warm-400 hover:text-warm-600 hover:bg-warm-200 transition-colors"
                title="Close browser panel"
              >
                <X size={14} />
              </button>
            </div>
          )}
        </div>
        <ChatArea />
        <InputBar />
      </div>

      {/* Draggable divider — fixed at the RIGHT EDGE of mainView,
          which is exactly the boundary between chat and browser.
          The divider is 12px wide for easy grabbing, with a 4px visual grip. */}
      {browserPanelVisible && (
        <div
          onMouseDown={handleDragStart}
          className="fixed top-0 bottom-0 flex items-center justify-center group"
          style={{
            right: 0,
            width: 12,
            cursor: "col-resize",
            zIndex: 50,
          }}
        >
          <div
            className="w-1 h-12 rounded-full bg-warm-300 group-hover:bg-accent-400 transition-colors"
          />
        </div>
      )}

      <SettingsModal />
    </div>
  );
};

export default App;
