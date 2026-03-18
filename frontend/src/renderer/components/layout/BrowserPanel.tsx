import React from "react";
import { Globe, X } from "lucide-react";
import { useStore } from "../../stores/store";

const BrowserPanel: React.FC = () => {
  const browserCurrentUrl = useStore((s) => s.browserCurrentUrl);
  const setBrowserPanelVisible = useStore((s) => s.setBrowserPanelVisible);

  const handleClose = async () => {
    // Only hide the panel UI — keep the backend CDP connection alive
    // so browser tools remain available for the agent
    try {
      await window.electronAPI.browserPanel.hide();
    } catch {
      // ignore
    }
    setBrowserPanelVisible(false);
  };

  return (
    <div className="flex-1 flex flex-col min-w-0 border-l border-warm-200">
      {/* Browser toolbar */}
      <div
        className="h-12 flex-shrink-0 border-b border-warm-200 flex items-center px-3 gap-2 bg-warm-50"
        style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
      >
        <Globe size={14} className="text-warm-400 flex-shrink-0" />
        <div
          className="flex-1 text-xs text-warm-500 truncate bg-white rounded-lg px-2.5 py-1.5 border border-warm-200"
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
        >
          {browserCurrentUrl || "about:blank"}
        </div>
        <button
          onClick={handleClose}
          className="p-1.5 rounded-lg text-warm-400 hover:text-warm-600 hover:bg-warm-200 transition-colors"
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
          title="Close browser panel"
        >
          <X size={14} />
        </button>
      </div>
      {/* This area is overlaid by the WebContentsView from Electron main process */}
      <div className="flex-1 bg-white flex items-center justify-center">
        <p className="text-warm-300 text-sm">Browser view active</p>
      </div>
    </div>
  );
};

export default BrowserPanel;
