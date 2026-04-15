import React, { useEffect, useState } from "react";
import { ArrowLeft, Edit, Trash2 } from "lucide-react";
import * as api from "../../services/api";
import { useStore } from "../../stores/store";
import MarkdownContent from "../chat/MarkdownContent";
import type { SkillDetail } from "../../types";

interface Props {
  name: string;
  onBack: () => void;
  onEdit: (name: string) => void;
  onDeleted: () => void;
}

const SkillDetailView: React.FC<Props> = ({ name, onBack, onEdit, onDeleted }) => {
  const [skill, setSkill] = useState<SkillDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const skillStats = useStore((s) => s.skillStats);
  const stats = skillStats[name];

  useEffect(() => {
    setLoading(true);
    api.fetchSkillDetail(name).then(setSkill).finally(() => setLoading(false));
  }, [name]);

  const handleDelete = async () => {
    if (!confirm(`Delete skill "${name}"?`)) return;
    await api.deleteSkill(name);
    onDeleted();
  };

  if (loading) return <div className="p-6 text-navy-light">Loading...</div>;
  if (!skill) return <div className="p-6 text-navy-light">Skill not found.</div>;

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-warm-200/40 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="p-1.5 rounded-lg text-navy-light hover:text-navy hover:bg-warm-200 transition-colors">
            <ArrowLeft size={16} />
          </button>
          <h1 className="text-lg font-bold text-navy">{skill.name}</h1>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => onEdit(name)}
            className="flex items-center gap-1 px-3 py-1.5 text-sm bg-warm-200/50 text-navy rounded-lg hover:bg-warm-200 transition-colors"
          >
            <Edit size={14} /> Edit
          </button>
          <button
            onClick={handleDelete}
            className="flex items-center gap-1 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50 rounded-lg transition-colors"
          >
            <Trash2 size={14} /> Delete
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4">
        <div className="flex flex-wrap items-center gap-3 mb-4 text-xs text-navy-light">
          <span className="bg-warm-100 px-2 py-0.5 rounded">{skill.agent_type}</span>
          <span>v{skill.version}</span>
          <span>by {skill.created_by}</span>
          {stats && <span>loads: {stats.loads}</span>}
          {skill.tags.map((t) => (
            <span key={t} className="bg-warm-200/50 px-1.5 py-0.5 rounded">{t}</span>
          ))}
        </div>
        <div className="prose prose-sm max-w-none">
          <MarkdownContent content={skill.content} />
        </div>
        {skill.files.length > 0 && (
          <div className="mt-6">
            <h3 className="text-sm font-semibold text-navy mb-2">Supporting Files</h3>
            <ul className="text-xs text-navy-light space-y-1">
              {skill.files.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
};

export default SkillDetailView;
