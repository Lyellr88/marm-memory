import { useEffect, useState } from 'react';
import { useLocation } from 'wouter';
import {
  Button,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/core';
import { Sparkles } from 'lucide-react';
import { useProjects } from '@/hooks/use-marm-queries';

/** Ask a question about an indexed project, from the Overview page.
 *
 *  Deliberately a one-line bar and not a card. The objection to putting this
 *  on Overview was that a tile which is mostly a text box competes with the
 *  counts that make the page useful — and that objection is right, so this
 *  does not sit in the card grid at all. It is a strip between the counts and
 *  the activity panels, the height of a single control.
 *
 *  It deep-links with `run=1` because the reader typed the question themselves;
 *  there is nothing to review before composing. The Project Explorer action
 *  does the opposite, and the difference is deliberate — see `SymbolActions`.
 */
export function AskBar() {
  const [, navigate] = useLocation();
  const { data: projects } = useProjects();
  const [task, setTask] = useState('');
  const [project, setProject] = useState('');

  // Same reason Code Context defaults its project: resolving from the server's
  // working directory is never the repository a reader has in mind.
  useEffect(() => {
    if (!project && projects?.length) setProject(projects[0].name);
  }, [project, projects]);

  if (!projects?.length) return null;

  const ask = () => {
    const trimmed = task.trim();
    if (!trimmed) return;
    const params = new URLSearchParams({ task: trimmed, project, run: '1' });
    navigate(`/code-context?${params.toString()}`);
  };

  return (
    <section
      className="flex shrink-0 flex-wrap items-center gap-3 rounded-xl border border-card-border bg-card/40 px-4 py-3"
      aria-label="Ask about a project"
    >
      <span className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">
        <Sparkles className="h-3 w-3" />
        Ask
      </span>
      <Input
        value={task}
        onChange={(event) => setTask(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') ask();
        }}
        placeholder="How does recall decide which memories to return?"
        aria-label="Question"
        maxLength={1000}
        className="min-w-[18rem] flex-1 border-transparent bg-background/65"
      />
      <Select value={project} onValueChange={setProject}>
        <SelectTrigger aria-label="Project" className="w-[210px] border-transparent bg-background/65">
          <SelectValue placeholder="Project" />
        </SelectTrigger>
        <SelectContent>
          {projects.map((item) => (
            <SelectItem key={item.name} value={item.name} title={item.name}>
              {item.display_name || item.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button onClick={ask} disabled={!task.trim()}>
        <Sparkles className="mr-2 h-4 w-4" /> Compose
      </Button>
    </section>
  );
}
