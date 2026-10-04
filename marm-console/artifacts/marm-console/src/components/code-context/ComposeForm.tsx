import { Sparkles } from 'lucide-react';
import { Button, Input, Label, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Textarea } from '@/components/ui/core';
import type { AnalystMode } from '@/lib/marm-types';

export const DEFAULT_BUDGET = 12000;
export const MAX_BUDGET = 100000;

/** Radix forbids `value=""` on a SelectItem, so the auto-detect option needs a
 *  sentinel. Kept rather than deleted: it is still correct for anyone running
 *  the Console from inside a repository rather than as a service. */
export const AUTO_PROJECT = '__auto__';

/** The composition answers a task, not a query, so the placeholder shows the
 *  shape that ranks well: a question about behaviour, not a symbol name. */
export const PLACEHOLDER = 'How does recall decide which memories to return?';

type ComposeFormProps = {
  task: string;
  setTask: (value: string) => void;
  project: string;
  setProject: (value: string) => void;
  sortedProjects: Array<{ name: string; display_name?: string | null }>;
  budget: number;
  setBudget: (value: number) => void;
  wantAnswer: boolean;
  setWantAnswer: (value: boolean) => void;
  analystMode: AnalystMode;
  setAnalystMode: (value: AnalystMode) => void;
  composing: boolean;
  onSubmit: (event: React.FormEvent) => void;
};

export function ComposeForm({ task, setTask, project, setProject, sortedProjects, budget, setBudget, wantAnswer, setWantAnswer, analystMode, setAnalystMode, composing, onSubmit }: ComposeFormProps) {
  return (
    <form onSubmit={onSubmit} className="mb-6 shrink-0 space-y-3">
      <div>
        <Label htmlFor="code-context-task">Task</Label>
        <Textarea
          id="code-context-task"
          value={task}
          onChange={(event) => setTask(event.target.value)}
          placeholder={PLACEHOLDER}
          rows={2}
          maxLength={1000}
          className="mt-1.5"
        />
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[16rem] flex-1">
          <Label htmlFor="code-context-project">Project</Label>
          <Select value={project} onValueChange={setProject}>
            <SelectTrigger id="code-context-project" aria-label="Project" className="mt-1.5">
              <SelectValue placeholder="Choose a project" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={AUTO_PROJECT}>Auto-detect from the Console's working directory</SelectItem>
              {sortedProjects.map((item) => (
                <SelectItem key={item.name} value={item.name} title={item.name}>
                  {item.display_name || item.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="w-40">
          <Label htmlFor="code-context-budget">Source budget</Label>
          <Input
            id="code-context-budget"
            type="number"
            min={500}
            max={MAX_BUDGET}
            step={500}
            value={budget}
            onChange={(event) => setBudget(Number(event.target.value))}
            className="mt-1.5"
          />
        </div>
        <label
          className="flex h-10 cursor-pointer select-none items-center gap-2 rounded-md border border-border/70 bg-muted/40 px-3 text-xs text-muted-foreground"
          title="Answer the question with the local model, grounded in the ranked context. Slower; the context itself does not need it."
        >
          <input
            type="checkbox"
            checked={wantAnswer}
            onChange={(event) => setWantAnswer(event.target.checked)}
            className="h-3.5 w-3.5 accent-[hsl(var(--primary))]"
          />
          Answer it too
        </label>
        <label className="flex h-10 items-center gap-2 text-xs text-muted-foreground">
          <span>Analyst</span>
          <select
            aria-label="Analyst"
            value={analystMode}
            disabled={!wantAnswer}
            onChange={(event) => setAnalystMode(event.target.value as AnalystMode)}
            title="Read-only returns the verified answer. Manual review also stages its verified results in Distill for you to approve. Guardrails lets MARM apply the ones it can prove mechanically, only where the operator enabled it. The model never applies anything."
            className="h-10 rounded-md border border-border/70 bg-muted/40 px-2 text-xs text-foreground disabled:opacity-50"
          >
            <option value="read_only">Read-only</option>
            <option value="manual_review">Manual review</option>
            <option value="guardrails">Guardrails</option>
          </select>
        </label>
        <Button type="submit" isLoading={composing} disabled={!task.trim()}>
          <Sparkles className="mr-2 h-4 w-4" /> Compose context
        </Button>
      </div>
    </form>
  );
}
