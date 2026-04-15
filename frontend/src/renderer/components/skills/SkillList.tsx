import React, { useEffect, useState } from "react";
import { Plus, Globe, Code, FileText, ArrowLeft } from "lucide-react";
import { useSkills } from "../../hooks/useSkills";
import { useStore } from "../../stores/store";
import type { SkillMeta } from "../../types";

const AGENT_ICONS: Record<string, React.ReactNode> = {
  browser: <Globe size={14} />,
  developer: <Code size={14} />,
  document: <FileText size={14} />,
};

const AGENT_COLORS: Record<string, string> = {
  browser: "bg-blue-100 text-blue-700",
  developer: "bg-green-100 text-green-700",
  document: "bg-amber-100 text-amber-700",
};

interface Props {
  onSelect: (name: string) => void;
  onNew: () => void;
  onBack: () => void;
}

const SkillList: React.FC<Props> = ({ onSelect, onNew, onBack }) => {
  const { skills, loading, refresh, toggleEnabled } = useSkills();
  const skillStats = useStore((s) => s.skillStats);
  const [filter, setFilter] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    refresh(filter || undefined);
  }, [filter, refresh]);

  const filtered = skills.filter((s) => {
    if (search) {
      const q = search.toLowerCase();
      return (
        s.name.includes(q) ||
        s.description.toLowerCase().includes(q) ||
        s.tags.some((t) => t.includes(q))
      );
    }
    return true;
  });

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-warm-200/40 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="p-1.5 rounded-lg text-navy-light hover:text-navy hover:bg-warm-200 transition-colors">
            <ArrowLeft size={16} />
          </button>
          <h1 className="text-lg font-bold text-navy">Skills</h1>
        </div>
        <button
          onClick={onNew}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-pastel-purple text-navy rounded-lg hover:bg-pastel-pink transition-colors"
        >
          <Plus size={14} /> New Skill
        </button>
      </div>

      <div className="px-6 py-3 flex items-center gap-2">
        {["All", "Browser", "Developer", "Document"].map((label) => {
          const value = label === "All" ? null : label.toLowerCase();
          const active = filter === value;
          return (
            <button
              key={label}
              onClick={() => setFilter(value)}
              className={`px-3 py-1 text-xs font-medium rounded-full transition-colors ${
                active
                  ? "bg-navy text-white"
                  : "bg-warm-200/50 text-navy-light hover:bg-warm-200"
              }`}
            >
              {label}
            </button>
          );
        })}
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search..."
          className="ml-auto px-3 py-1 text-sm bg-warm-100 border border-warm-200/40 rounded-lg outline-none focus:border-navy/30 w-48"
        />
      </div>

      <div className="flex-1 overflow-y-auto px-6 pb-6 space-y-2">
        {loading && <div className="text-navy-light text-sm py-8 text-center">Loading...</div>}
        {!loading && filtered.length === 0 && (
          <div className="text-navy-light text-sm py-8 text-center">
            No skills yet. Create one or let agents learn from task execution.
          </div>
        )}
        {filtered.map((skill) => (
          <SkillCard
            key={skill.name}
            skill={skill}
            stats={skillStats[skill.name]}
            onClick={() => onSelect(skill.name)}
            onToggle={(enabled) => toggleEnabled(skill.name, enabled)}
          />
        ))}
      </div>
    </div>
  );
};

const SkillCard: React.FC<{
  skill: SkillMeta;
  stats?: { loads: number; patches: number };
  onClick: () => void;
  onToggle: (enabled: boolean) => void;
}> = ({ skill, stats, onClick, onToggle }) => (
  <div
    onClick={onClick}
    className="p-4 bg-white rounded-xl border border-warm-200/40 hover:border-navy/20 cursor-pointer transition-colors"
  >
    <div className="flex items-center justify-between mb-1">
      <div className="flex items-center gap-2">
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full ${AGENT_COLORS[skill.agent_type]}`}>
          {AGENT_ICONS[skill.agent_type]} {skill.agent_type}
        </span>
        <span className="font-semibold text-sm text-navy">{skill.name}</span>
        <span className="text-[11px] text-navy-light">v{skill.version}</span>
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); onToggle(!skill.enabled); }}
        className={`text-[11px] px-2 py-0.5 rounded-full ${
          skill.enabled ? "bg-green-100 text-green-700" : "bg-warm-200 text-navy-light"
        }`}
      >
        {skill.enabled ? "enabled" : "disabled"}
      </button>
    </div>
    <p className="text-xs text-navy-light mb-2">{skill.description}</p>
    <div className="flex items-center gap-3 text-[11px] text-navy-light">
      {skill.tags.map((t) => (
        <span key={t} className="bg-warm-100 px-1.5 py-0.5 rounded">{t}</span>
      ))}
      {stats && <span className="ml-auto">loads: {stats.loads}</span>}
      <span className="text-navy-light/50">{skill.created_by}</span>
    </div>
  </div>
);

export default SkillList;
