import React from "react";
import { Loader2, CheckCircle, XCircle, Clock, ListTodo } from "lucide-react";
import type { SubTask } from "../../types";

interface Props {
  subTasks: SubTask[];
}

const stateIcon: Record<string, React.ReactNode> = {
  open: <Clock size={12} className="text-warm-400" />,
  waiting: <Clock size={12} className="text-warning" />,
  running: <Loader2 size={12} className="text-accent-500 animate-spin" />,
  done: <CheckCircle size={12} className="text-pastel-green" />,
  failed: <XCircle size={12} className="text-danger-500" />,
};

const TaskProgress: React.FC<Props> = ({ subTasks }) => {
  if (!subTasks.length) return null;

  const completed = subTasks.filter(
    (t) => t.state === "done" || t.state === "failed"
  ).length;
  const progress = Math.round((completed / subTasks.length) * 100);

  return (
    <div className="mb-3">
      <div className="flex items-center gap-2 mb-2">
        <ListTodo size={14} className="text-warm-500" />
        <span className="text-xs font-bold text-navy-light">
          Tasks ({completed}/{subTasks.length})
        </span>
        <div className="flex-1 h-1.5 bg-warm-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-accent-500 rounded-full transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>
      <div className="space-y-1">
        {subTasks.map((task) => (
          <div key={task.id} className="flex items-start gap-2 text-xs">
            <div className="flex-shrink-0 mt-0.5">
              {stateIcon[task.state] || stateIcon.open}
            </div>
            <div className="min-w-0">
              <span className="text-navy-light">{task.content}</span>
              {task.assigneeId && (
                <span className="text-warm-400 ml-1">
                  [{task.assigneeId}]
                </span>
              )}
              {task.result && task.state === "done" && (
                <div className="text-warm-400 mt-0.5 truncate">
                  {task.result}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default TaskProgress;
