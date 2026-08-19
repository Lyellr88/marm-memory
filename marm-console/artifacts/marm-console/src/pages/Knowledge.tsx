import { useState } from 'react';
import { Button, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/core';
import { Layers, X } from 'lucide-react';
import { ExplorerTab } from '@/components/knowledge/ExplorerTab';
import { BuildConceptsDialog, DuplicatesTab } from '@/components/knowledge/BuildAndDuplicates';
import type { ConceptBuildRun } from '@/lib/marm-types';

export function KnowledgePage() {
  const [buildOpen, setBuildOpen] = useState(false);
  const [buildJobId, setBuildJobId] = useState<string | null>(null);
  const [buildNotice, setBuildNotice] = useState<string | null>(null);

  const handleBuildComplete = (job: ConceptBuildRun) => {
    if (job.status === 'success') {
      setBuildNotice(`Concept build finished: ${job.entities_extracted} entities and ${job.relationships_created} relationships.`);
      return;
    }
    setBuildNotice(`Concept build ${job.status}${job.error_code ? `: ${job.error_code}` : '.'}`);
  };

  return (
    <div className="p-8 flex flex-col h-full overflow-hidden">
      <div className="flex justify-between items-center mb-8 shrink-0">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Knowledge Graph</h1>
          <p className="text-muted-foreground text-sm mt-1">Extracted semantic network</p>
        </div>
        <Button onClick={() => setBuildOpen(true)} variant="secondary">
          <Layers className="w-4 h-4 mr-2" /> Build Concepts
        </Button>
      </div>

      <Tabs defaultValue="explorer" className="flex-1 flex flex-col overflow-hidden">
        <TabsList className="self-start shrink-0 mb-4 bg-transparent border-b rounded-none w-full justify-start p-0 h-auto">
          <TabsTrigger value="explorer" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none py-3 px-6">
            Explorer
          </TabsTrigger>
          <TabsTrigger value="duplicates" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none py-3 px-6">
            Duplicate Review
          </TabsTrigger>
        </TabsList>

        <div className="flex-1 overflow-hidden min-h-0">
          <TabsContent value="explorer" className="m-0 h-full">
            <ExplorerTab />
          </TabsContent>
          <TabsContent value="duplicates" className="m-0 h-full">
            <DuplicatesTab />
          </TabsContent>
        </div>
      </Tabs>

      {buildNotice && (
        <div role="status" className="fixed right-6 top-6 z-50 flex max-w-md items-start gap-3 rounded-md border bg-background p-4 shadow-lg">
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
