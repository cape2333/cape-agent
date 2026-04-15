import React, { useEffect, useState } from "react";
import { ArrowLeft, Save } from "lucide-react";
import * as api from "../../services/api";

interface Props {
  name?: string;
  onBack: () => void;
  onSaved: (name: string) => void;
}

const SkillEditor: React.FC<Props> = ({ name: editName, onBack, onSaved }) => {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [agentType, setAgentType] = useState<"browser" | "developer" | "document">("browser");
  const [content, setContent] = useState("");
  const [tags, setTags] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const isEdit = !!editName;

  useEffect(() => {
    if (editName) {
      api.fetchSkillDetail(editName).then((skill) => {
        setName(skill.name);
        setDescription(skill.description);
        setAgentType(skill.agent_type);
        setContent(skill.content);
        setTags(skill.tags.join(", "));
      });
    }
  }, [editName]);

  const handleSave = async () => {
    setError("");
    setSaving(true);
    try {
      if (isEdit) {
        await api.updateSkill(editName!, {
          description,
          content,
          tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
        });
        onSaved(editName!);
      } else {
        const created = await api.createSkill({
          name,
          description,
          agent_type: agentType,
          content,
          tags: tags.split(",").map((t) => t.trim()).filter(Boolean),
        });
        onSaved(created.name);
      }
    } catch (e: any) {
      setError(e.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="px-6 py-4 border-b border-warm-200/40 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="p-1.5 rounded-lg text-navy-light hover:text-navy hover:bg-warm-200 transition-colors">
            <ArrowLeft size={16} />
          </button>
          <h1 className="text-lg font-bold text-navy">{isEdit ? "Edit Skill" : "New Skill"}</h1>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-pastel-purple text-navy rounded-lg hover:bg-pastel-pink transition-colors disabled:opacity-50"
        >
          <Save size={14} /> {saving ? "Saving..." : "Save"}
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {error && <div className="text-red-600 text-sm bg-red-50 px-3 py-2 rounded-lg">{error}</div>}

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-navy-light mb-1">Name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={isEdit}
              placeholder="my-skill-name"
              className="w-full px-3 py-2 text-sm bg-warm-100 border border-warm-200/40 rounded-lg outline-none focus:border-navy/30 disabled:opacity-50"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-navy-light mb-1">Agent Type</label>
            <select
              value={agentType}
              onChange={(e) => setAgentType(e.target.value as any)}
              disabled={isEdit}
              className="w-full px-3 py-2 text-sm bg-warm-100 border border-warm-200/40 rounded-lg outline-none focus:border-navy/30 disabled:opacity-50"
            >
              <option value="browser">Browser</option>
              <option value="developer">Developer</option>
              <option value="document">Document</option>
            </select>
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-navy-light mb-1">Description</label>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="One-line description of what this skill does"
            className="w-full px-3 py-2 text-sm bg-warm-100 border border-warm-200/40 rounded-lg outline-none focus:border-navy/30"
          />
        </div>

        <div>
          <label className="block text-xs font-medium text-navy-light mb-1">Tags (comma separated)</label>
          <input
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="search, academic, google"
            className="w-full px-3 py-2 text-sm bg-warm-100 border border-warm-200/40 rounded-lg outline-none focus:border-navy/30"
          />
        </div>

        <div className="flex-1">
          <label className="block text-xs font-medium text-navy-light mb-1">Content (Markdown)</label>
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={"## Trigger Conditions\nWhen to use this skill.\n\n## Steps\n1. First step\n2. Second step\n\n## Pitfalls\n- Known issue\n\n## Verification\n- How to confirm success"}
            className="w-full h-96 px-3 py-2 text-sm font-mono bg-warm-100 border border-warm-200/40 rounded-lg outline-none focus:border-navy/30 resize-y"
          />
        </div>
      </div>
    </div>
  );
};

export default SkillEditor;
