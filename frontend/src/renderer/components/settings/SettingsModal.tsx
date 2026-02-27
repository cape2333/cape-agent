import React, { useState, useEffect } from "react";
import { X, Plus } from "lucide-react";
import { useSettings } from "../../hooks/useSettings";
import ProviderForm from "./ProviderForm";
import type { AppSettings, ProviderSettings } from "../../types";

const SettingsModal: React.FC = () => {
  const { settings, saveSettings, showSettings, setShowSettings } = useSettings();
  const [draft, setDraft] = useState<AppSettings>(settings);

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
    const newActive = draft.active_provider_index >= updated.length
      ? Math.max(0, updated.length - 1)
      : draft.active_provider_index > index
        ? draft.active_provider_index - 1
        : draft.active_provider_index;
    setDraft({ providers: updated, active_provider_index: newActive });
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

  const handleSave = async () => {
    await saveSettings(draft);
    setShowSettings(false);
  };

  return (
    <div className="fixed inset-0 bg-warm-900/30 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="bg-white border border-warm-200 rounded-2xl w-full max-w-lg max-h-[80vh] flex flex-col shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-warm-200">
          <h2 className="text-lg font-semibold text-warm-800">Settings</h2>
          <button
            onClick={() => setShowSettings(false)}
            className="text-warm-400 hover:text-warm-700 transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-warm-600">Model Providers</h3>
            <button
              onClick={addProvider}
              className="flex items-center gap-1 text-sm text-accent-500 hover:text-accent-600 font-medium"
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
            <p className="text-sm text-warm-400 text-center py-4">
              No providers configured. Add one to get started.
            </p>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-warm-200 flex justify-end gap-3">
          <button
            onClick={() => setShowSettings(false)}
            className="px-4 py-2 text-sm text-warm-500 hover:text-warm-700 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="px-5 py-2 text-sm bg-accent-500 hover:bg-accent-600 text-white rounded-xl font-medium transition-colors"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
};

export default SettingsModal;
