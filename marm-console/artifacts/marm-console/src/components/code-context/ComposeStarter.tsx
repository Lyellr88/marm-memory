import { Network } from 'lucide-react';
import { Button } from '@/components/ui/core';
import { Panel, SectionHeading, SmallStat } from '@/components/ui/panels';
import type { ProjectSummary } from '@/lib/marm-types';

/** Behaviour questions, not symbol names: ranking is seeded from the task's own
 *  words, so "how does X decide Y" composes a better neighbourhood than "X". */
const EXAMPLE_TASKS = [
  'How does recall decide which memories to return?',
  'Where is the distinctiveness gate applied?',
  'What would changing the ranking weights affect?',
];

export function ComposeStarter({ setTask, selected }: { setTask: (value: string) => void; selected: ProjectSummary | undefined }) {
  return (
    <div className="mt-6 space-y-6">
      <section className="space-y-3">
        <SectionHeading
          title="Try one"
          description="Ranking is seeded from the task's own words, so a question about behaviour composes better context than a bare symbol name."
        />
        <div className="flex flex-wrap gap-2">
          {EXAMPLE_TASKS.map((example) => (
            <Button key={example} type="button" variant="outline" size="sm" onClick={() => setTask(example)}>
              {example}
            </Button>
          ))}
        </div>
      </section>

      {selected && (
        <Panel
          icon={<Network className="h-5 w-5 text-violet-300" />}
          title={`Will search ${selected.display_name || selected.name}`}
          description={selected.root_path}
          alert={selected.status !== 'ready'}
        >
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <SmallStat label="Graph nodes" value={selected.nodes.toLocaleString()} caption="Files and symbols" />
            <SmallStat label="Graph edges" value={selected.edges.toLocaleString()} caption="Calls and imports" />
            <SmallStat
              label="Index status"
              value={selected.status}
              tone={selected.status === 'ready' ? 'good' : 'warn'}
            />
          </div>
        </Panel>
      )}
    </div>
  );
}
