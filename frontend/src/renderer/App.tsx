import React, { useEffect } from "react";
import { PanelLeftOpen } from "lucide-react";
import Sidebar from "./components/layout/Sidebar";
import ChatArea from "./components/layout/ChatArea";
import InputBar from "./components/layout/InputBar";
import SettingsModal from "./components/settings/SettingsModal";
import { useStore } from "./stores/store";
import { initApiUrl } from "./services/api";

const App: React.FC = () => {
  const sidebarCollapsed = useStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useStore((s) => s.toggleSidebar);
  const theme = useStore((s) => s.settings.theme);
  useEffect(() => {
    initApiUrl();
  }, []);

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
    <div className="flex h-full bg-warm-100 text-navy">
      <div
        className="sidebar-transition flex-shrink-0 overflow-hidden"
        style={{ width: sidebarCollapsed ? 0 : 320 }}
      >
        <div className="h-full" style={{ width: 320 }}>
          <div className="h-full bg-surface border-r border-warm-200/40 overflow-hidden">
            <Sidebar />
          </div>
        </div>
      </div>
      <div className="flex-1 flex flex-col min-w-0">
        {/* Drag region for macOS title bar */}
        <div
          className="h-12 flex-shrink-0 flex items-center justify-between"
          style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
        >
          {sidebarCollapsed ? (
            <div
              className="flex items-center gap-1"
              style={{ marginLeft: 80 }}
            >
              <button
                onClick={toggleSidebar}
                className="p-1.5 rounded-lg text-navy-light hover:text-navy hover:bg-warm-200 transition-colors"
                style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
                title="Open sidebar"
              >
                <PanelLeftOpen size={16} />
              </button>
            </div>
          ) : (
            <div />
          )}
          <div />
        </div>
        <ChatArea />
        <InputBar />
      </div>

      <SettingsModal />
    </div>
  );
};

export default App;
