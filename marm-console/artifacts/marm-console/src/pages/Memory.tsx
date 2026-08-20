import { useState } from 'react';
import { BookOpenText, Database, Layers3, ScrollText, Waypoints } from 'lucide-react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/core';
import { useOverview } from '@/hooks/use-marm-queries';
import { MemoriesTab } from '@/components/memory/MemoriesTab';
import { SessionsTab, LogsTab } from '@/components/memory/SessionsAndLogsTabs';
import { NotebookTab, CompactionTab } from '@/components/memory/NotebookAndCompactionTabs';

type MemoryTab = 'memories' | 'notebook' | 'logs' | 'sessions' | 'compaction';

export function MemoryPage() {
  const [activeTab, setActiveTab] = useState<MemoryTab>('memories');
  const { data: overview } = useOverview();
  const storedMemories = overview
    ? overview.memory.active_memories + overview.memory.compacted_sources
    : null;
  const tabs = [
    { value: 'memories', label: 'Stored Memories', detail: 'Retrievable context', count: storedMemories, icon: Database, tone: 'memory-tab-cyan' },
    { value: 'notebook', label: 'Notebook', detail: 'Pinned knowledge', count: overview?.memory.notebook_entries ?? null, icon: BookOpenText, tone: 'memory-tab-violet' },
    { value: 'logs', label: 'Logs', detail: 'Structured history', count: overview?.memory.log_entries ?? null, icon: ScrollText, tone: 'memory-tab-blue' },
    { value: 'sessions', label: 'Sessions', detail: 'Context workspaces', count: overview?.memory.sessions ?? null, icon: Waypoints, tone: 'memory-tab-emerald' },
    { value: 'compaction', label: 'Compaction', detail: 'Pending summaries', count: overview?.memory.pending_compaction ?? null, icon: Layers3, tone: 'memory-tab-amber' },
  ] as const;

  return (
    <div className="page-enter flex h-full flex-col overflow-hidden p-7 xl:p-8">
      <div className="mx-auto flex h-full w-full max-w-[1560px] flex-col overflow-hidden">
        <header className="mb-6 shrink-0">
          <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">
            <Database className="h-3 w-3" />
            Context control
          </div>
          <h1 className="text-[1.8rem] font-semibold tracking-[-0.045em]">Memories</h1>
          <p className="mt-1 text-sm text-muted-foreground">Stored context, notebooks, logs, sessions, and compaction.</p>
        </header>

        <Tabs value={activeTab} onValueChange={(value) => setActiveTab(value as MemoryTab)} className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <TabsList className="mb-4 grid h-auto w-full shrink-0 grid-cols-5 gap-1.5 rounded-xl border border-card-border bg-card/70 p-1.5 shadow-[0_14px_40px_rgba(0,0,0,0.16),inset_0_1px_0_rgba(var(--primary-rgb),0.04)]">
            {tabs.map((tab, index) => (
              <TabsTrigger
                key={tab.value}
                value={tab.value}
                className={`memory-tab metric-enter group relative h-[58px] justify-start gap-3 overflow-hidden border border-transparent px-3 text-left data-[state=active]:bg-white/[0.035] ${tab.tone}`}
                style={{ animationDelay: `${index * 45}ms` }}
              >
                <span className="memory-tab-icon flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border bg-background/45 transition-transform duration-200 group-hover:scale-105">
                  <tab.icon className="h-3.5 w-3.5" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-semibold text-foreground">{tab.label}</span>
                  <span className="mt-0.5 block truncate text-[10px] font-normal text-muted-foreground">{tab.detail}</span>
                </span>
                <span className="font-mono text-sm font-semibold tabular-nums text-foreground/90">
                  {tab.count === null ? '—' : tab.count.toLocaleString()}
                </span>
              </TabsTrigger>
            ))}
          </TabsList>

          <div className="min-h-0 flex-1 overflow-hidden">
            <TabsContent value="memories" className="m-0 h-full">
              <MemoriesTab />
            </TabsContent>
            <TabsContent value="notebook" className="m-0 h-full">
              <NotebookTab />
            </TabsContent>
            <TabsContent value="logs" className="m-0 h-full">
              <LogsTab />
            </TabsContent>
            <TabsContent value="sessions" className="m-0 h-full">
              <SessionsTab />
            </TabsContent>
            <TabsContent value="compaction" className="m-0 h-full">
              <CompactionTab />
            </TabsContent>
          </div>
        </Tabs>
      </div>
    </div>
  );
}
