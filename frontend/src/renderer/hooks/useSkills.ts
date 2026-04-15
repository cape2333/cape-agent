import { useCallback, useState } from "react";
import { useStore } from "../stores/store";
import * as api from "../services/api";
import type { SkillCreate, SkillUpdate } from "../types";

export function useSkills() {
  const skills = useStore((s) => s.skills);
  const setSkills = useStore((s) => s.setSkills);
  const setSkillStats = useStore((s) => s.setSkillStats);
  const updateSkillInList = useStore((s) => s.updateSkillInList);
  const removeSkillFromList = useStore((s) => s.removeSkillFromList);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async (agentType?: string) => {
    setLoading(true);
    try {
      const [list, stats] = await Promise.all([
        api.fetchSkills(agentType),
        api.fetchSkillStats(),
      ]);
      setSkills(list);
      setSkillStats(stats);
    } finally {
      setLoading(false);
    }
  }, [setSkills, setSkillStats]);

  const create = useCallback(async (data: SkillCreate) => {
    const created = await api.createSkill(data);
    await refresh();
    return created;
  }, [refresh]);

  const update = useCallback(async (name: string, data: SkillUpdate) => {
    const updated = await api.updateSkill(name, data);
    updateSkillInList(updated);
    return updated;
  }, [updateSkillInList]);

  const remove = useCallback(async (name: string) => {
    await api.deleteSkill(name);
    removeSkillFromList(name);
  }, [removeSkillFromList]);

  const toggleEnabled = useCallback(async (name: string, enabled: boolean) => {
    const updated = await api.updateSkill(name, { enabled });
    updateSkillInList(updated);
  }, [updateSkillInList]);

  return { skills, loading, refresh, create, update, remove, toggleEnabled };
}
