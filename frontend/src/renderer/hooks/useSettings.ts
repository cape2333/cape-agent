import { useCallback, useEffect } from "react";
import { useStore } from "../stores/store";
import * as api from "../services/api";

export function useSettings() {
  const { settings, setSettings, showSettings, setShowSettings } = useStore();

  const loadSettings = useCallback(async () => {
    try {
      const s = await api.fetchSettings();
      setSettings({ ...s, theme: s.theme || settings.theme });
    } catch {
      // use defaults
    }
  }, [setSettings, settings.theme]);

  const saveSettings = useCallback(
    async (newSettings: typeof settings) => {
      try {
        const saved = await api.updateSettings(newSettings);
        setSettings({ ...saved, theme: newSettings.theme });
      } catch {
        // Apply settings locally even if backend is unavailable
        setSettings(newSettings);
      }
    },
    [setSettings]
  );

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  return { settings, saveSettings, showSettings, setShowSettings };
}
