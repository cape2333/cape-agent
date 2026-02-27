import { useCallback, useEffect } from "react";
import { useStore } from "../stores/store";
import * as api from "../services/api";

export function useSettings() {
  const { settings, setSettings, showSettings, setShowSettings } = useStore();

  const loadSettings = useCallback(async () => {
    try {
      const s = await api.fetchSettings();
      setSettings(s);
    } catch {
      // use defaults
    }
  }, [setSettings]);

  const saveSettings = useCallback(
    async (newSettings: typeof settings) => {
      const saved = await api.updateSettings(newSettings);
      setSettings(saved);
    },
    [setSettings]
  );

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  return { settings, saveSettings, showSettings, setShowSettings };
}
