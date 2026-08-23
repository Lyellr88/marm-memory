import { useEffect, useState } from 'react';
import { FolderCode } from 'lucide-react';
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

  return project && <CodeGraphExplorer
    key={project.name}
    project={project}
    projects={projects}
    projectName={projectName}
    onProjectChange={setProjectName}
    graph={graph}
    isLoading={graphLoading}
    isError={graphFailed}
  />;
}
