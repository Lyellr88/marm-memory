import { useEffect, useState } from 'react';
import { FolderCode, Network } from 'lucide-react';
import { Card, CardContent, Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/core';
import { useProjectGraph, useProjects } from '@/hooks/use-marm-queries';
import { CodeGraphExplorer } from './CodeGraphExplorer';

export function CodeExplorerTab() {
  const { data: projects, isLoading: projectsLoading } = useProjects();
  const [projectName, setProjectName] = useState<string>('');
  const project = projects?.find((item) => item.name === projectName) || null;
  const { data: graph, isLoading: graphLoading, isError: graphFailed } = useProjectGraph(project?.name || '', !!project);

  useEffect(() => {
    if (!projects?.length) {
      setProjectName('');
      return;
    }
    if (!projects.some((item) => item.name === projectName)) setProjectName(projects[0].name);
  }, [projectName, projects]);

  if (projectsLoading) return <div className="flex h-full items-center justify-center text-sm text-muted-foreground">Loading indexed projects…</div>;
  if (!projects?.length) return <div className="flex h-full flex-col items-center justify-center rounded-xl border border-dashed p-10 text-center"><FolderCode className="mb-4 h-10 w-10 text-muted-foreground/60" /><h2 className="text-lg font-medium">Index a repository to explore its code graph</h2><p className="mt-2 max-w-md text-sm text-muted-foreground">The Code Graph is independent of memory concepts. Once a repository is indexed, select it here to inspect its file and import topology.</p></div>;

  return <div className="flex h-full min-h-0 flex-col gap-4">
    <Card className="shrink-0 border-cyan-400/20 bg-[linear-gradient(105deg,rgba(8,47,73,.28),transparent_58%)]">
      <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-3"><div className="rounded-lg border border-cyan-400/25 bg-cyan-400/10 p-2 text-cyan-200"><Network className="h-4 w-4" /></div><div><p className="text-sm font-semibold">Code Explorer</p><p className="text-xs text-muted-foreground">An indexed repository’s structural graph, separate from memory-derived concepts.</p></div></div>
        <Select value={projectName} onValueChange={setProjectName}><SelectTrigger className="w-full sm:w-[21rem]"><SelectValue placeholder="Select indexed repository" /></SelectTrigger><SelectContent>{projects.map((item) => <SelectItem key={item.name} value={item.name}>{item.name}</SelectItem>)}</SelectContent></Select>
      </CardContent>
    </Card>
    {project && <CodeGraphExplorer project={project} graph={graph} isLoading={graphLoading} isError={graphFailed} />}
  </div>;
}
