import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/core';
import { Layers, X } from 'lucide-react';
import { ExplorerTab } from '@/components/knowledge/ExplorerTab';
import { BuildConceptsDialog, DuplicatesTab } from '@/components/knowledge/BuildAndDuplicates';
import { CodeExplorerTab } from '@/components/code/CodeExplorerTab';
import { queryKeys, useMarmConfig, useProjects } from '@/hooks/use-marm-queries';
import type { ConceptBuildRun, ConceptGraphScope } from '@/lib/marm-types';

function useDefaultCodeGraphPreload() {
  const queryClient = useQueryClient();
  const { baseUrl, client } = useMarmConfig();
  const { data: projects } = useProjects();

  useEffect(() => {
    const project = projects?.[0];
    if (!project) return;
    void queryClient.prefetchQuery({
      queryKey: queryKeys.projectGraph(baseUrl, project.name),
      queryFn: () => client.getProjectGraph(project.name),
      staleTime: Infinity,
    });
  }, [baseUrl, client, projects, queryClient]);
}

export function KnowledgePage() {
  const [buildOpen, setBuildOpen] = useState(false);
  const [buildJobId, setBuildJobId] = useState<string | null>(null);
  const [buildNotice, setBuildNotice] = useState<string | null>(null);
  const [graphScope, setGraphScope] = useState<ConceptGraphScope>({ type: 'all' });

  useDefaultCodeGraphPreload();

  const handleBuildComplete = (job: ConceptBuildRun) => {
    if (job.status === 'success') {
      setGraphScope(
        job.scope_type === 'all'
          ? { type: 'all' }
          : { type: job.scope_type, value: job.scope_value || '' },
      );
      setBuildNotice(`Concept build finished: ${job.entities_extracted} entities and ${job.relationships_created} relationships.`);
      return;
    }
    setBuildNotice(`Concept build ${job.status}${job.error_code ? `: ${job.error_code}` : '.'}`);
  };

  return (
    <div className="page-enter p-7 xl:p-8 flex flex-col h-full overflow-hidden">
      <div className="mb-6 shrink-0">
        <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">Semantic intelligence</div>
        <h1 className="text-[1.8rem] font-semibold tracking-[-0.045em]">Knowledge Graph</h1>
        <p className="text-muted-foreground text-sm mt-1">Explore memory concepts, indexed code structure, provenance, and duplicate concepts.</p>
      </div>

      <Tabs defaultValue="memory" className="flex-1 flex flex-col overflow-hidden">
        <div className="flex shrink-0 items-center justify-between gap-4 border-b mb-4">
          <TabsList className="self-start bg-transparent border-0 rounded-none justify-start p-0 h-auto">
            <TabsTrigger value="memory" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent py-3 px-5">
              Memory Explorer
            </TabsTrigger>
            <TabsTrigger value="code" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent py-3 px-5">
              Code Explorer
            </TabsTrigger>
            <TabsTrigger value="duplicates" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent py-3 px-5">
              Potential Duplicates
            </TabsTrigger>
          </TabsList>
          <Button onClick={() => setBuildOpen(true)} variant="secondary" className="shrink-0">
            <Layers className="w-4 h-4 mr-2" /> Build Concepts
          </Button>
        </div>

        <div className="flex-1 overflow-hidden min-h-0">
          <TabsContent value="memory" className="m-0 h-full">
            <ExplorerTab scope={graphScope} onScopeChange={setGraphScope} />
          </TabsContent>
          <TabsContent value="code" className="m-0 h-full">
            <CodeExplorerTab />
          </TabsContent>
          <TabsContent value="duplicates" className="m-0 h-full">
            <DuplicatesTab />
          </TabsContent>
        </div>
      </Tabs>

      {buildNotice && (
        <div role="status" className="success-pop fixed right-6 top-6 z-50 flex max-w-md items-start gap-3 rounded-lg border border-primary/25 bg-[#0a1421] p-4 shadow-[0_20px_55px_rgba(0,0,0,0.45)]">
          <p className="text-sm">{buildNotice}</p>
          <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" onClick={() => setBuildNotice(null)} aria-label="Dismiss build notification">
            <X className="h-4 w-4" />
          </Button>
        </div>
      )}

      <BuildConceptsDialog
        open={buildOpen}
        onOpenChange={setBuildOpen}
        jobId={buildJobId}
        onJobIdChange={setBuildJobId}
        onComplete={handleBuildComplete}
      />
    </div>
  );
}
