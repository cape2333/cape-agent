import React from "react";
import { Sun, Moon, Monitor } from "lucide-react";
import type { AppSettings } from "../../types";

const THEME_OPTIONS = [
  { value: "light" as const, label: "Light", icon: Sun },
  { value: "dark" as const, label: "Dark", icon: Moon },
  { value: "system" as const, label: "System", icon: Monitor },
];

interface Props {
  draft: AppSettings;
  onUpdate: (settings: AppSettings) => void;
}

const GeneralSettings: React.FC<Props> = ({ draft, onUpdate }) => {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-medium text-warm-600 mb-1">Appearance</h3>
        <p className="text-xs text-warm-400 mb-4">
          Choose how Cape looks to you.
        </p>
        <div className="border border-warm-200 rounded-xl p-4 bg-warm-50">
          <label className="block text-xs text-warm-500 mb-3 font-medium">
            Theme
          </label>
          <div className="flex gap-3">
            {THEME_OPTIONS.map((opt) => {
              const Icon = opt.icon;
              const isSelected = draft.theme === opt.value;
              return (
                <button
                  key={opt.value}
                  onClick={() => onUpdate({ ...draft, theme: opt.value })}
                  className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors border ${
                    isSelected
                      ? "border-accent-500 bg-accent-500/10 text-accent-600"
                      : "border-warm-200 bg-white text-warm-600 hover:bg-warm-100"
                  }`}
                >
                  <Icon size={16} />
                  {opt.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
};

export default GeneralSettings;
