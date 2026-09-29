import { useState } from 'react';
import { useSearchParams } from 'wouter';
import { Plus } from 'lucide-react';
import { useConnectionsOverview } from '@/hooks/use-marm-queries';
import { Button, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/core';
import { AddConnectionDialog } from './AddConnectionDialog';
import { DockerTab } from './DockerTab';
import { ManualTab } from './ManualTab';
import { SetupTab } from './SetupTab';
import { StatusStrip } from './StatusStrip';

type ConnectionsTab = 'setup' | 'docker' | 'manual';

const CONNECTIONS_TABS: ConnectionsTab[] = ['setup', 'docker', 'manual'];
const TAB_CLASS = 'rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent py-3 px-5';

export function ConnectionsPage() {
  const [params, setParams] = useSearchParams();
  const requested = params.get('tab') as ConnectionsTab | null;
  const tab: ConnectionsTab = requested && CONNECTIONS_TABS.includes(requested) ? requested : 'setup';
  const setTab = (next: ConnectionsTab) => {
    const updated = new URLSearchParams(params);
    updated.set('tab', next);
    setParams(updated, { replace: true });
  };
  const overview = useConnectionsOverview();
  const [addOpen, setAddOpen] = useState(false);

  return (
    <div className="page-enter flex h-full flex-col overflow-hidden p-7 xl:p-8">
      <div className="mb-4 flex shrink-0 flex-wrap items-end justify-between gap-4">
        <div>
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">Setup</div>
          <h1 className="text-[1.8rem] font-semibold tracking-[-0.045em]">Connections</h1>
          <p className="mt-1 max-w-[68ch] text-sm text-muted-foreground">Set up how MARM runs and connect every AI tool you use. Everything here can also be done by hand from the Manual tab.</p>
        </div>
        <Button variant="outline" onClick={() => setAddOpen(true)}><Plus className="mr-2 h-4 w-4" />Add a connection</Button>
      </div>

      <StatusStrip overview={overview.data} />

      <Tabs value={tab} onValueChange={(value) => setTab(value as ConnectionsTab)} className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <TabsList className="mb-4 h-auto w-full shrink-0 justify-start self-start rounded-none border-x-0 border-t-0 border-b bg-transparent p-0">
          <TabsTrigger value="setup" className={TAB_CLASS}>Setup</TabsTrigger>
          <TabsTrigger value="docker" className={TAB_CLASS}>Docker</TabsTrigger>
          <TabsTrigger value="manual" className={TAB_CLASS}>Manual</TabsTrigger>
        </TabsList>

        <div className="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
          <TabsContent value="setup" className="m-0">
            <SetupTab overview={overview.data} onRequestConnection={() => setAddOpen(true)} />
          </TabsContent>
          <TabsContent value="docker" className="m-0">
            <DockerTab onRequestConnection={() => setAddOpen(true)} />
          </TabsContent>
          <TabsContent value="manual" className="m-0">
            <ManualTab />
          </TabsContent>
        </div>
      </Tabs>

      <AddConnectionDialog open={addOpen} onOpenChange={setAddOpen} overview={overview.data} />
    </div>
  );
}
