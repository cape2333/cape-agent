import React from "react";
import { Sun, Moon, Monitor } from "lucide-react";
import { useStore } from "../../stores/store";
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
  const setSettings = useStore((s) => s.setSettings);

  const handleThemeChange = (theme: AppSettings["theme"]) => {
    const updated = { ...draft, theme };
    onUpdate(updated);
    // Apply theme immediately (don't wait for Save + API)
    setSettings(updated);
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-sm font-bold text-navy mb-1">Appearance</h3>
        <p className="text-xs text-navy-light mb-4">
          Choose how Cape looks to you.
        </p>
        <div className="border border-warm-200/60 rounded-2xl p-5 bg-warm-50">
          <label className="block text-xs text-navy-light mb-3 font-bold">
            Theme
          </label>
          <div className="flex gap-3">
            {THEME_OPTIONS.map((opt) => {
              const Icon = opt.icon;
              const isSelected = draft.theme === opt.value;
              return (
                <button
                  key={opt.value}
                  onClick={() => handleThemeChange(opt.value)}
                  className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-2xl text-sm font-bold transition-colors border ${
                    isSelected
                      ? "border-navy bg-navy/5 text-navy"
                      : "border-warm-200 bg-surface text-navy-light hover:bg-warm-100"
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
