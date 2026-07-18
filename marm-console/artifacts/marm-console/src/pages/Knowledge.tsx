import { useState } from 'react';
import { Button, Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/core';
import { Layers } from 'lucide-react';
import { ExplorerTab } from '@/components/knowledge/ExplorerTab';
import { BuildConceptsDialog, DuplicatesTab } from '@/components/knowledge/BuildAndDuplicates';

export function KnowledgePage() {
  const [buildOpen, setBuildOpen] = useState(false);

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

      <BuildConceptsDialog open={buildOpen} onOpenChange={setBuildOpen} />
    </div>
  );
}
