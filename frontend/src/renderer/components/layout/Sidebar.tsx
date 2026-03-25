import React from "react";
import { PanelLeftClose, Plus, Trash2, Settings } from "lucide-react";
import { useConversations } from "../../hooks/useConversations";
import { useStore } from "../../stores/store";

const Sidebar: React.FC = () => {
  const { conversations, activeConversationId, createNew, select, remove } =
    useConversations();
  const setShowSettings = useStore((s) => s.setShowSettings);
  const toggleSidebar = useStore((s) => s.toggleSidebar);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div
        className="px-6 pt-8 pb-4 flex items-center justify-between"
        style={{ WebkitAppRegion: "drag" } as React.CSSProperties}
      >
        <div
          className="flex items-center"
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
        >
          <span className="font-extrabold text-xl tracking-tight text-navy">Cape Agent</span>
        </div>
        <div
          className="flex items-center gap-2"
          style={{ WebkitAppRegion: "no-drag" } as React.CSSProperties}
        >
          <button
            onClick={toggleSidebar}
            className="p-1.5 rounded-lg text-navy-light hover:text-navy hover:bg-warm-100 transition-colors"
            title="Toggle sidebar"
          >
            <PanelLeftClose size={16} />
          </button>
          <button
            onClick={createNew}
            className="new-chat-btn-animated w-10 h-10 rounded-full bg-pastel-purple flex items-center justify-center text-navy hover:bg-pastel-pink cursor-pointer border-none"
            title="New chat"
          >
            <Plus size={18} strokeWidth={2.5} />
          </button>
        </div>
      </div>

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto px-4 pb-6 space-y-2">
        {conversations.length > 0 && (
          <div className="text-[12px] font-extrabold text-navy pl-3 mb-1 mt-2">
            Conversations
          </div>
        )}
        {conversations.map((conv) => {
          const isActive = activeConversationId === conv.id;
          return (
            <div
              key={conv.id}
              onClick={() => select(conv.id)}
              className={`group flex items-center gap-2 px-5 py-4 rounded-3xl cursor-pointer ${
                isActive
                  ? "bg-pastel-green text-navy"
                  : "text-navy hover:bg-navy/[0.03] history-item-hover"
              }`}
            >
              <div className="flex-1 min-w-0 flex flex-col gap-1.5">
                <span className="text-[15px] font-bold leading-snug line-clamp-2 text-navy">
                  {conv.title}
                </span>
                <span className="text-[12px] font-semibold text-navy-light">
                  {isActive ? "Context active" : "\u00A0"}
                </span>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  remove(conv.id);
                }}
                className="flex-shrink-0 opacity-0 group-hover:opacity-100 hover:text-danger-500 transition-opacity p-1"
              >
                <Trash2 size={14} />
              </button>
            </div>
          );
        })}
      </div>

      {/* Settings button */}
      <div className="px-4 pb-4">
        <button
          onClick={() => setShowSettings(true)}
          className="flex items-center gap-2 px-4 py-2.5 text-sm font-semibold text-navy-light hover:text-navy transition-colors rounded-2xl hover:bg-warm-100 w-full"
        >
          <Settings size={16} />
          Settings
        </button>
      </div>
    </div>
  );
};

export default Sidebar;
