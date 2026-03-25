import React from "react";
import { Trash2 } from "lucide-react";
import type { ProviderSettings } from "../../types";

const PROVIDER_OPTIONS = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "gemini", label: "Google Gemini" },
  { value: "deepseek", label: "DeepSeek" },
  { value: "groq", label: "Groq" },
  { value: "mistral", label: "Mistral" },
  { value: "ollama", label: "Ollama" },
  { value: "minimax", label: "MiniMax" },
];

interface Props {
  provider: ProviderSettings;
  index: number;
  isActive: boolean;
  onUpdate: (index: number, provider: ProviderSettings) => void;
  onRemove: (index: number) => void;
  onSetActive: (index: number) => void;
}

const ProviderForm: React.FC<Props> = ({
  provider,
  index,
  isActive,
  onUpdate,
  onRemove,
  onSetActive,
}) => {
  const update = (field: keyof ProviderSettings, value: string) => {
    onUpdate(index, { ...provider, [field]: value });
  };

  return (
    <div
      className={`p-5 rounded-2xl border ${
        isActive ? "border-navy bg-navy/[0.02]" : "border-warm-200/60 bg-warm-50"
      }`}
    >
      <div className="flex items-center justify-between mb-3">
        <button
          onClick={() => onSetActive(index)}
          className={`text-sm px-4 py-1.5 rounded-full font-bold transition-colors ${
            isActive
              ? "bg-navy text-warm-100"
              : "bg-warm-200 text-navy-light hover:bg-warm-300"
          }`}
        >
          {isActive ? "Active" : "Set Active"}
        </button>
        <button
          onClick={() => onRemove(index)}
          className="text-navy-light hover:text-danger-500 transition-colors p-1"
        >
          <Trash2 size={16} />
        </button>
      </div>

      <div className="space-y-3">
        <div>
          <label className="block text-xs text-navy-light mb-1 font-bold">Provider</label>
          <select
            value={provider.provider}
            onChange={(e) => update("provider", e.target.value)}
            className="w-full bg-surface border border-warm-200 rounded-xl px-3 py-2.5 text-sm text-navy outline-none focus:border-navy transition-colors"
          >
            {PROVIDER_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-xs text-navy-light mb-1 font-bold">Model</label>
          <input
            type="text"
            value={provider.model}
            onChange={(e) => update("model", e.target.value)}
            placeholder="e.g. gpt-4o-mini"
            className="w-full bg-surface border border-warm-200 rounded-xl px-3 py-2.5 text-sm text-navy outline-none focus:border-navy transition-colors placeholder-warm-400"
          />
        </div>

        <div>
          <label className="block text-xs text-navy-light mb-1 font-bold">API Key</label>
          <input
            type="password"
            value={provider.api_key}
            onChange={(e) => update("api_key", e.target.value)}
            placeholder="sk-..."
            className="w-full bg-surface border border-warm-200 rounded-xl px-3 py-2.5 text-sm text-navy outline-none focus:border-navy transition-colors placeholder-warm-400"
          />
        </div>

        <div>
          <label className="block text-xs text-navy-light mb-1 font-bold">
            API Base URL (optional)
          </label>
          <input
            type="text"
            value={provider.api_base || ""}
            onChange={(e) => update("api_base", e.target.value)}
            placeholder="https://api.openai.com/v1"
            className="w-full bg-surface border border-warm-200 rounded-xl px-3 py-2.5 text-sm text-navy outline-none focus:border-navy transition-colors placeholder-warm-400"
          />
        </div>
      </div>
    </div>
  );
};

export default ProviderForm;
