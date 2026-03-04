import React from "react";
import { PanelLeftClose, Search, SquarePen, Trash2, Settings, MessageSquare } from "lucide-react";
import { useConversations } from "../../hooks/useConversations";
import { useStore } from "../../stores/store";

const Sidebar: React.FC = () => {
  const { conversations, activeConversationId, createNew, select, remove } =
    useConversations();
  const setShowSettings = useStore((s) => s.setShowSettings);
  const toggleSidebar = useStore((s) => s.toggleSidebar);

  return (
    <div className="flex flex-col h-full">
      {/* Drag region for macOS title bar */}
      <div
        className="h-12 flex-shrink-0 flex items-center justify-end gap-1 px-3"
        style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
      >
        <button
          onClick={toggleSidebar}
          className="p-1.5 rounded-lg text-warm-400 hover:text-warm-600 hover:bg-warm-100 transition-colors"
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
          title="Toggle sidebar"
        >
          <PanelLeftClose size={16} />
        </button>
        <button
          className="p-1.5 rounded-lg text-warm-400 hover:text-warm-600 hover:bg-warm-100 transition-colors"
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
          title="Search"
        >
          <Search size={16} />
        </button>
        <button
          onClick={createNew}
          className="p-1.5 rounded-lg text-warm-400 hover:text-warm-600 hover:bg-warm-100 transition-colors"
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
          title="New chat"
        >
          <SquarePen size={16} />
        </button>
      </div>

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto px-2 space-y-0.5">
        {conversations.map((conv) => (
          <div
            key={conv.id}
            onClick={() => select(conv.id)}
            className={`group flex items-center gap-2 px-3 py-2.5 rounded-xl cursor-pointer text-sm transition-colors ${
              activeConversationId === conv.id
                ? "bg-warm-150 text-warm-800 font-medium"
                : "text-warm-500 hover:bg-warm-100 hover:text-warm-700"
            }`}
          >
            <MessageSquare size={14} className="flex-shrink-0" />
            <span className="flex-1 truncate">{conv.title}</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                remove(conv.id);
              }}
              className="opacity-0 group-hover:opacity-100 hover:text-danger-500 transition-opacity"
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
      </div>

      {/* Settings button */}
      <div className="p-3">
        <button
          onClick={() => setShowSettings(true)}
          className="flex items-center gap-2 px-3 py-2 text-sm text-warm-400 hover:text-warm-700 transition-colors"
        >
          <Settings size={16} />
          Settings
        </button>
      </div>
    </div>
  );
};

export default Sidebar;
