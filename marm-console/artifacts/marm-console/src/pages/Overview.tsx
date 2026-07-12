import { useOverview, useFilters, useMarmConfig, isAuthError } from '@/hooks/use-marm-queries';
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton, Badge, Button } from '@/components/ui/core';
import { Link } from 'wouter';
import { SettingsDialog } from '@/components/layout/SettingsDialog';
import { useState } from 'react';
import { Database, Network, FolderCode, Activity, HardDrive, Cpu, AlertTriangle, Layers, KeyRound } from 'lucide-react';

const CONCEPT_STATUS_LABEL: Record<string, string> = {
  ready: 'Ready',
  not_built: 'Not Built',
  unavailable: 'Unavailable',
};
const GRAPH_STATUS_LABEL: Record<string, string> = {
  ready: 'Ready',
  starting: 'Starting',
  disabled: 'Disabled',
  error: 'Error',
};
function statusBadgeVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'ready') return 'default';
  if (status === 'error' || status === 'unavailable') return 'destructive';
  if (status === 'starting' || status === 'not_built') return 'secondary';
  return 'outline';
}
import { formatDistanceToNow } from 'date-fns';

export function OverviewPage() {
  const { data: overview, isLoading, error } = useOverview();
  const { data: filters } = useFilters();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { baseUrl } = useMarmConfig();

  if (error) {
    const authError = isAuthError(error);
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center h-full">
        {authError ? (
          <KeyRound className="w-12 h-12 text-amber-500 mb-4 opacity-80" />
        ) : (
          <AlertTriangle className="w-12 h-12 text-destructive mb-4 opacity-80" />
        )}
        <h2 className="text-xl font-semibold mb-2">{authError ? "Authentication Required" : "Connection Error"}</h2>
        <p className="text-muted-foreground max-w-md mb-6">
          {authError 
            ? `The server at ${baseUrl} requires an API key.` 
            : `Could not connect to the MARM backend at ${baseUrl}. Make sure your local server is running.`}
        </p>
        <Button onClick={() => setSettingsOpen(true)}>
          {authError ? "Enter API Key" : "Configure Connection"}
        </Button>
        <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      </div>
    );
  }

  if (isLoading || !overview) {
    return (
      <div className="p-8 space-y-6 flex-1 overflow-auto">
        <h1 className="text-2xl font-bold tracking-tight mb-6">System Status</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <Card key={i}><CardHeader className="pb-2"><Skeleton className="h-4 w-24 mb-2" /><Skeleton className="h-8 w-16" /></CardHeader></Card>
          ))}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mt-6">
          <Card className="h-64"><CardContent className="p-6"><Skeleton className="h-full w-full" /></CardContent></Card>
          <Card className="h-64"><CardContent className="p-6"><Skeleton className="h-full w-full" /></CardContent></Card>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 space-y-8 flex-1 overflow-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Overview</h1>
          <p className="text-muted-foreground text-sm mt-1">System telemetry and memory health</p>
        </div>
        <div className="flex items-center gap-4">
          <Badge variant={overview.mcp_status?.reachable ? "default" : "destructive"} className="px-3 py-1 uppercase tracking-wider text-[10px]">
            {overview.mcp_status?.reachable ? 'MCP Online' : 'MCP Offline'}
          </Badge>
          {overview.mcp_status?.latency_ms !== undefined && (
            <span className="text-xs text-muted-foreground font-mono bg-muted px-2 py-1 rounded">
              {overview.mcp_status.latency_ms.toFixed(1)}ms ping
            </span>
          )}
        </div>
      </div>

      {/* Primary Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card className="bg-card/50 backdrop-blur border-primary/20">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Stored Memories</CardTitle>
            <Database className="w-4 h-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {(overview.memory.active_memories + overview.memory.compacted_sources).toLocaleString()}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {overview.memory.active_memories.toLocaleString()} active, {overview.memory.compacted_sources.toLocaleString()} compacted sources
            </p>
          </CardContent>
        </Card>
        
        <Card className="bg-card/50 backdrop-blur">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Concepts</CardTitle>
            <Network className="w-4 h-4 text-accent-foreground" />
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div className="text-2xl font-bold">{overview.concepts.entities.toLocaleString()}</div>
              <Badge variant={statusBadgeVariant(overview.concepts.status)} className="text-[10px] uppercase">
                {CONCEPT_STATUS_LABEL[overview.concepts.status] || overview.concepts.status}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-1">{overview.concepts.relationships.toLocaleString()} relationships</p>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Indexed Projects</CardTitle>
            <FolderCode className="w-4 h-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <div className="text-2xl font-bold">{overview.graph.projects.length}</div>
              <Badge variant={statusBadgeVariant(overview.graph.status)} className="text-[10px] uppercase">
                {GRAPH_STATUS_LABEL[overview.graph.status] || overview.graph.status}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground mt-1">Code graph {overview.graph.status}</p>
          </CardContent>
        </Card>

        <Card className="bg-card/50 backdrop-blur">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Pending Compaction</CardTitle>
            <Layers className="w-4 h-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{overview.memory.pending_compaction.toLocaleString()}</div>
            <p className="text-xs text-muted-foreground mt-1">{overview.memory.compacted_sources.toLocaleString()} previously compacted</p>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Concept Builds */}
        <Card className="flex flex-col">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Recent Concept Builds</CardTitle>
                <CardDescription>Knowledge extraction jobs</CardDescription>
              </div>
              <Link href="/knowledge" className="text-xs text-primary hover:underline">View All</Link>
            </div>
          </CardHeader>
          <CardContent className="flex-1">
            {overview.concepts.recent_builds.length === 0 ? (
              <div className="h-full flex items-center justify-center text-sm text-muted-foreground border border-dashed rounded-md p-8">
                No recent builds
              </div>
            ) : (
              <div className="space-y-4">
                {overview.concepts.recent_builds.slice(0, 5).map(build => (
                  <div key={build.id} className="flex items-center justify-between p-3 rounded-lg border bg-muted/30">
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center gap-2">
                        <Badge variant={build.status === 'success' ? 'default' : build.status === 'error' ? 'destructive' : 'outline'} className="text-[10px] uppercase">
                          {build.status}
                        </Badge>
                        <span className="text-sm font-mono">{build.scope_value || 'Global'}</span>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        +{build.entities_extracted} nodes, +{build.relationships_created} edges
                      </span>
                    </div>
                    <div className="text-xs text-muted-foreground whitespace-nowrap text-right">
                      <div>{formatDistanceToNow(new Date(build.created_at), { addSuffix: true })}</div>
                      {build.duration_ms && <div>{(build.duration_ms / 1000).toFixed(1)}s</div>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Indexed Projects */}
        <Card className="flex flex-col">
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle>Indexed Contexts</CardTitle>
                <CardDescription>Active workspaces</CardDescription>
              </div>
              <Link href="/projects" className="text-xs text-primary hover:underline">Manage</Link>
            </div>
          </CardHeader>
          <CardContent className="flex-1">
            {overview.graph.projects.length === 0 ? (
              <div className="h-full flex items-center justify-center text-sm text-muted-foreground border border-dashed rounded-md p-8">
                No indexed projects
              </div>
            ) : (
              <div className="space-y-3">
                {overview.graph.projects.map(proj => (
                  <Link key={proj.name} href={`/projects`} className="block">
                    <div className="flex items-center justify-between p-3 rounded-lg border bg-muted/30 hover:bg-muted/50 transition-colors cursor-pointer group">
                      <div className="flex items-center gap-3">
                        <div className="p-2 bg-background rounded border group-hover:border-primary/50 transition-colors">
                          <HardDrive className="w-4 h-4 text-muted-foreground" />
                        </div>
                        <div>
                          <div className="font-mono text-sm font-medium">{proj.name}</div>
                          <div className="text-xs text-muted-foreground truncate max-w-[200px]">{proj.root_path}</div>
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-xs font-medium">{proj.nodes.toLocaleString()} nodes</div>
                        <div className="text-xs text-muted-foreground">{proj.edges.toLocaleString()} edges</div>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* System info footer */}
      <div className="flex items-center justify-between text-xs text-muted-foreground border-t pt-4">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1"><Cpu className="w-3 h-3" /> Mode: <span className="font-mono uppercase">{overview.runtime_mode}</span></span>
        </div>
        <div>MARM MCP Server {overview.mcp_status?.version}</div>
      </div>
    </div>
  );
}
