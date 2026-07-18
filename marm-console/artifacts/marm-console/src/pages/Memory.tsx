import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/core';
import { MemoriesTab } from '@/components/memory/MemoriesTab';
import { SessionsTab, LogsTab } from '@/components/memory/SessionsAndLogsTabs';
import { NotebookTab, CompactionTab } from '@/components/memory/NotebookAndCompactionTabs';

export function MemoryPage() {
  return (
    <div className="p-8 flex flex-col h-full overflow-hidden">
      <div className="mb-8 shrink-0">
        <h1 className="text-2xl font-bold tracking-tight">Memory Management</h1>
        <p className="text-muted-foreground text-sm mt-1">Raw context, sessions, logs, and summarization</p>
      </div>

      <Tabs defaultValue="memories" className="flex-1 flex flex-col overflow-hidden">
        <TabsList className="self-start shrink-0 mb-4 bg-transparent border-b rounded-none w-full justify-start p-0 h-auto">
          <TabsTrigger value="memories" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none py-3 px-6">
            Raw Memories
          </TabsTrigger>
          <TabsTrigger value="sessions" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none py-3 px-6">
            Sessions
          </TabsTrigger>
          <TabsTrigger value="logs" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none py-3 px-6">
            Logs
          </TabsTrigger>
          <TabsTrigger value="notebook" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none py-3 px-6">
            Notebook
          </TabsTrigger>
          <TabsTrigger value="compaction" className="rounded-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:shadow-none py-3 px-6">
            Compaction
          </TabsTrigger>
        </TabsList>
        
        <div className="flex-1 overflow-hidden min-h-0">
          <TabsContent value="memories" className="m-0 h-full">
            <MemoriesTab />
          </TabsContent>
          <TabsContent value="sessions" className="m-0 h-full">
            <SessionsTab />
          </TabsContent>
          <TabsContent value="logs" className="m-0 h-full">
            <LogsTab />
          </TabsContent>
          <TabsContent value="notebook" className="m-0 h-full">
            <NotebookTab />
          </TabsContent>
          <TabsContent value="compaction" className="m-0 h-full">
            <CompactionTab />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
