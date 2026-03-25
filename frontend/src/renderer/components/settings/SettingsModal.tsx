import React, { useState, useEffect } from "react";
import { X, Plus, Settings, Box, type LucideIcon } from "lucide-react";
import { useSettings } from "../../hooks/useSettings";
import ProviderForm from "./ProviderForm";
import GeneralSettings from "./GeneralSettings";
import type { AppSettings, ProviderSettings } from "../../types";

type TabId = "general" | "providers";

const TABS: { id: TabId; label: string; icon: LucideIcon }[] = [
  { id: "general", label: "General", icon: Settings },
  { id: "providers", label: "Providers", icon: Box },
];

const SettingsModal: React.FC = () => {
  const { settings, saveSettings, showSettings, setShowSettings } = useSettings();
  const [draft, setDraft] = useState<AppSettings>(settings);
  const [activeTab, setActiveTab] = useState<TabId>("general");

  useEffect(() => {
    setDraft(settings);
  }, [settings, showSettings]);

  if (!showSettings) return null;

  const updateProvider = (index: number, provider: ProviderSettings) => {
    const updated = [...draft.providers];
    updated[index] = provider;
    setDraft({ ...draft, providers: updated });
  };

  const removeProvider = (index: number) => {
    const updated = draft.providers.filter((_, i) => i !== index);
    const newActive =
      draft.active_provider_index >= updated.length
        ? Math.max(0, updated.length - 1)
        : draft.active_provider_index > index
          ? draft.active_provider_index - 1
          : draft.active_provider_index;
    setDraft({ ...draft, providers: updated, active_provider_index: newActive });
  };

  const addProvider = () => {
    setDraft({
      ...draft,
      providers: [
        ...draft.providers,
        { provider: "openai", model: "gpt-4o-mini", api_key: "" },
      ],
    });
  };

  const handleClose = () => {
    setDraft(settings);
    setShowSettings(false);
  };

  const handleSave = async () => {
    await saveSettings(draft);
    setShowSettings(false);
  };

  return (
    <div className="fixed inset-0 bg-navy/20 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-surface border border-warm-200/60 rounded-3xl w-full max-w-3xl h-[90vh] flex flex-col shadow-[0_25px_60px_rgba(5,25,45,0.12)]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-warm-200/40">
          <h2 className="text-lg font-extrabold text-navy">Settings</h2>
          <button
            onClick={handleClose}
            className="text-navy-light hover:text-navy transition-colors p-1 rounded-full hover:bg-warm-100"
          >
            <X size={20} />
          </button>
        </div>

        {/* Body: Sidebar + Content */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left sidebar */}
          <nav className="w-48 flex-shrink-0 bg-warm-50 border-r border-warm-200/40 p-3 space-y-1">
            {TABS.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-2xl text-sm font-bold transition-colors ${
                    isActive
                      ? "bg-surface text-navy shadow-[0_4px_15px_rgba(5,25,45,0.04)] border border-warm-200/60"
                      : "text-navy-light hover:text-navy hover:bg-warm-100"
                  }`}
                >
                  <Icon size={16} />
                  {tab.label}
                </button>
              );
            })}
          </nav>

          {/* Right content */}
          <div className="flex-1 overflow-y-auto p-6">
            {activeTab === "general" && (
              <GeneralSettings draft={draft} onUpdate={setDraft} />
            )}

            {activeTab === "providers" && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-bold text-navy-light">
                    Model Providers
                  </h3>
                  <button
                    onClick={addProvider}
                    className="flex items-center gap-1 text-sm text-accent-500 hover:text-accent-600 font-bold"
                  >
                    <Plus size={14} />
                    Add
                  </button>
                </div>

                {draft.providers.map((prov, i) => (
                  <ProviderForm
                    key={i}
                    provider={prov}
                    index={i}
                    isActive={i === draft.active_provider_index}
                    onUpdate={updateProvider}
                    onRemove={removeProvider}
                    onSetActive={(idx) =>
                      setDraft({ ...draft, active_provider_index: idx })
                    }
                  />
                ))}

                {draft.providers.length === 0 && (
                  <p className="text-sm text-navy-light text-center py-4">
                    No providers configured. Add one to get started.
                  </p>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-warm-200/40 flex justify-end">
          <div className="flex gap-3">
            <button
              onClick={handleClose}
              className="px-5 py-2.5 text-sm font-bold text-navy-light hover:text-navy transition-colors rounded-full hover:bg-warm-100"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              className="px-6 py-2.5 text-sm bg-navy hover:opacity-80 text-warm-100 rounded-full font-bold transition-colors"
            >
              Save
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SettingsModal;
