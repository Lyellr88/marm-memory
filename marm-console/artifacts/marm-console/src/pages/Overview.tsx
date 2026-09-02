import { useId, useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { Link } from 'wouter';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Cpu,
  Database,
  FolderCode,
  GitBranch,
  HardDrive,
  KeyRound,
  Layers,
  Network,
  Radio,
} from 'lucide-react';
import { useFilters, useMarmConfig, useOverview, isAuthError } from '@/hooks/use-marm-queries';
import { SettingsDialog } from '@/components/layout/SettingsDialog';
import { Badge, Button, Card, CardContent, CardHeader, Skeleton, cn } from '@/components/ui/core';
import { StatCard } from '@/components/ui/panels';

const CONCEPT_STATUS_LABEL: Record<string, string> = {
  ready: 'Ready',
  not_built: 'Not built',
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

function SparseTelemetryField({ tone = 'cyan' }: { tone?: 'cyan' | 'teal' }) {
  const id = useId().replaceAll(':', '');
  const color = tone === 'teal' ? '#2dd4bf' : 'var(--primary)';
  const rows = [
    'M-55 178 C65 98 170 98 282 166 C386 229 474 211 572 137 C676 59 764 82 858 139',
    'M-55 198 C66 118 171 117 284 185 C389 248 478 230 577 156 C681 78 769 101 858 158',
    'M-55 219 C68 139 174 138 288 206 C394 269 484 251 583 177 C687 99 774 122 858 179',
    'M-55 241 C70 161 178 160 293 228 C400 291 490 273 590 199 C694 121 780 144 858 201',
    'M-55 264 C73 184 182 183 299 251 C406 314 497 296 597 222 C701 144 786 167 858 224',
    'M-55 288 C76 208 187 207 305 275 C413 338 504 320 604 246 C708 168 792 191 858 248',
    'M-55 313 C80 233 192 232 312 300 C420 363 511 345 612 271 C716 193 798 216 858 273',
  ];
  const columns = [
    'M20 346 C38 282 50 210 73 125',
    'M86 346 C99 278 105 202 135 105',
    'M153 346 C161 274 164 197 198 103',
    'M220 346 C224 271 223 197 260 139',
    'M287 346 C286 274 280 205 321 190',
    'M354 346 C348 280 337 217 382 216',
    'M421 346 C411 285 397 225 444 211',
    'M488 346 C474 281 458 211 506 185',
    'M555 346 C538 273 520 193 568 141',
    'M622 346 C603 268 584 181 630 99',
    'M689 346 C668 269 648 182 692 78',
    'M756 346 C734 276 713 195 754 87',
    'M823 346 C800 286 778 213 816 119',
  ];

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[68%] overflow-hidden" aria-hidden="true">
      <div className="absolute inset-0" style={{ background: 'radial-gradient(ellipse at 50% 88%, rgba(var(--primary-rgb), 0.10), transparent 65%)' }} />
      <svg className="absolute inset-x-[-4%] bottom-[-8%] h-[116%] w-[108%]" viewBox="0 0 800 340" preserveAspectRatio="none">
        <defs>
          <linearGradient id={`${id}-stroke`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={color} stopOpacity="0.06" />
            <stop offset="0.48" stopColor={color} stopOpacity="0.32" />
            <stop offset="1" stopColor={color} stopOpacity="0.12" />
          </linearGradient>
          <linearGradient id={`${id}-fill`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={color} stopOpacity="0" />
            <stop offset="1" stopColor={color} stopOpacity="0.045" />
          </linearGradient>
          <filter id={`${id}-glow`} x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="2.4" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        <path d={`${rows[0]} L858 352 L-55 352 Z`} fill={`url(#${id}-fill)`} />

        <g fill="none" stroke={`url(#${id}-stroke)`} strokeWidth="0.72">
          {rows.map((path) => <path key={path} d={path} />)}
          {columns.map((path) => <path key={path} d={path} />)}
        </g>

        <g fill="none" stroke={color} strokeLinecap="round">
          <path d={rows[1]} strokeWidth="2.4" strokeDasharray="0.1 8" opacity="0.62" />
          <path d={rows[3]} strokeWidth="1.8" strokeDasharray="0.1 9" opacity="0.46" />
          <path d={rows[5]} strokeWidth="1.4" strokeDasharray="0.1 10" opacity="0.28" />
          <path d={columns[2]} strokeWidth="1.4" strokeDasharray="0.1 12" opacity="0.26" />
          <path d={columns[9]} strokeWidth="1.5" strokeDasharray="0.1 11" opacity="0.3" />
        </g>

        <g fill={color} filter={`url(#${id}-glow)`}>
          <circle cx="66" cy="118" r="1.7" opacity="0.5" />
          <circle cx="171" cy="117" r="1.9" opacity="0.56" />
          <circle cx="284" cy="185" r="2.2" opacity="0.72" />
          <circle cx="478" cy="230" r="1.8" opacity="0.48" />
          <circle cx="577" cy="156" r="2.5" opacity="0.82" />
          <circle cx="681" cy="78" r="1.8" opacity="0.6" />
          <circle cx="769" cy="101" r="1.5" opacity="0.48" />
          <circle cx="182" cy="183" r="1.5" opacity="0.42" />
          <circle cx="400" cy="291" r="2.1" opacity="0.58" />
          <circle cx="694" cy="121" r="2" opacity="0.64" />
        </g>
      </svg>
    </div>
  );
}

export function OverviewPage() {
  const { data: overview, isLoading, error } = useOverview();
  useFilters();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const { baseUrl } = useMarmConfig();

  if (error) {
    const authError = isAuthError(error);
    return (
      <div className="page-enter flex h-full flex-1 flex-col items-center justify-center p-8 text-center">
        <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-xl border border-amber-400/20 bg-amber-400/[0.06]">
          {authError ? <KeyRound className="h-6 w-6 text-amber-400" /> : <AlertTriangle className="h-6 w-6 text-destructive" />}
        </div>
        <h2 className="text-xl font-semibold">{authError ? 'Authentication required' : 'Connection unavailable'}</h2>
        <p className="mt-2 max-w-md text-muted-foreground">
          {authError
            ? `The server at ${baseUrl} requires an API key.`
            : `MARM Console could not reach the backend at ${baseUrl}.`}
        </p>
        <Button className="mt-6" onClick={() => setSettingsOpen(true)}>
          {authError ? 'Enter API key' : 'Configure connection'}
        </Button>
        <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
      </div>
    );
  }

  if (isLoading || !overview) {
    return (
      <div className="page-enter flex-1 space-y-6 overflow-auto p-8">
        <div className="space-y-2"><Skeleton className="h-8 w-36" /><Skeleton className="h-4 w-64" /></div>
        <div className="grid grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((item) => <Skeleton key={item} className="h-36 rounded-xl" />)}
        </div>
        <div className="grid grid-cols-2 gap-5"><Skeleton className="h-80 rounded-xl" /><Skeleton className="h-80 rounded-xl" /></div>
      </div>
    );
  }

  const reachable = Boolean(overview.mcp_status?.reachable);
  const storedMemories = overview.memory.active_memories + overview.memory.compacted_sources;

  return (
    <div className="page-enter h-full flex-1 overflow-auto p-7 xl:p-8">
      <div className="mx-auto flex min-h-full max-w-[1560px] flex-col gap-6">
        <header className="flex items-start justify-between gap-6">
          <div>
            <div className="mb-2 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-primary/80">
              <Radio className="h-3 w-3" />
              System command
            </div>
            <h1 className="text-[1.8rem] font-semibold tracking-[-0.045em]">Overview</h1>
            <p className="mt-1 text-sm text-muted-foreground">Memory health, graph readiness, and local runtime activity.</p>
          </div>
        </header>

        <section className="grid grid-cols-4 gap-4" aria-label="System metrics">
          <StatCard label="Stored memories" value={storedMemories.toLocaleString()} detail={`${overview.memory.active_memories.toLocaleString()} active · ${overview.memory.compacted_sources.toLocaleString()} compacted sources`} icon={<Database className="h-5 w-5" />} delay={0} />
          <StatCard label="Concepts" value={overview.concepts.entities.toLocaleString()} detail={`${overview.concepts.relationships.toLocaleString()} relationships`} icon={<Network className="h-5 w-5" />} tone="teal" delay={50} status={<Badge variant={statusBadgeVariant(overview.concepts.status)} className="mb-0.5 text-[9px] uppercase">{CONCEPT_STATUS_LABEL[overview.concepts.status] || overview.concepts.status}</Badge>} />
          <StatCard label="Indexed projects" value={overview.graph.projects.length.toLocaleString()} detail={`Code graph ${overview.graph.status}`} icon={<FolderCode className="h-5 w-5" />} tone="blue" delay={100} status={<Badge variant={statusBadgeVariant(overview.graph.status)} className="mb-0.5 text-[9px] uppercase">{GRAPH_STATUS_LABEL[overview.graph.status] || overview.graph.status}</Badge>} />
          <StatCard label="Pending compaction" value={overview.memory.pending_compaction.toLocaleString()} detail={`${overview.memory.compacted_sources.toLocaleString()} previously compacted`} icon={<Layers className="h-5 w-5" />} tone="amber" delay={150} />
        </section>

        <section className="grid min-h-[360px] flex-1 grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)] gap-5">
          <Card className="relative flex h-full flex-col overflow-hidden border-t-2 border-t-emerald-400/35 shadow-[0_18px_55px_rgba(0,0,0,0.2),inset_0_1px_0_rgba(45,212,191,0.05)]">
            <CardHeader className="border-b border-border/70 px-5 py-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="font-semibold tracking-tight">Recent concept builds</h2>
                  <p className="mt-1 text-xs text-muted-foreground">Latest knowledge extraction activity</p>
                </div>
                <Link href="/knowledge" className="group flex items-center gap-1 text-xs font-medium text-primary hover:text-primary-highlight">
                  View all <ChevronRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
                </Link>
              </div>
            </CardHeader>
            <CardContent className="relative flex-1 p-3">
              {overview.concepts.recent_builds.length <= 2 && <SparseTelemetryField tone="teal" />}
              {overview.concepts.recent_builds.length === 0 ? (
                <div className="relative z-10 flex h-full min-h-64 items-start justify-center pt-12 text-sm text-muted-foreground">No concept builds yet</div>
              ) : (
                <div className="relative z-10 space-y-1">
                  {overview.concepts.recent_builds.slice(0, 5).map((build) => (
                    <div key={build.id} className="group flex items-center justify-between rounded-lg border border-transparent px-3 py-3 transition-colors hover:border-border/80 hover:bg-primary/[0.025]">
                      <div className="flex min-w-0 items-center gap-3">
                        <div className={cn('flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border', build.status === 'success' ? 'border-emerald-400/20 bg-emerald-400/[0.06] text-emerald-400' : build.status === 'error' ? 'border-destructive/20 bg-destructive/[0.06] text-destructive' : 'border-primary/20 bg-primary/[0.06] text-primary')}>
                          {build.status === 'success' ? <CheckCircle2 className="h-4 w-4" /> : <Network className="h-4 w-4" />}
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <Badge variant={build.status === 'success' ? 'default' : build.status === 'error' ? 'destructive' : 'outline'} className="text-[9px] uppercase">{build.status}</Badge>
                            <span className="truncate font-mono text-xs text-foreground">{build.scope_value || 'Global'}</span>
                          </div>
                          <div className="mt-1 text-[11px] text-muted-foreground">+{build.entities_extracted} nodes · +{build.relationships_created} edges</div>
                        </div>
                      </div>
                      <div className="shrink-0 text-right text-[11px] text-muted-foreground">
                        <div>{formatDistanceToNow(new Date(build.created_at), { addSuffix: true })}</div>
                        <div className="mt-1 font-mono">{build.duration_ms ? `${(build.duration_ms / 1000).toFixed(1)}s` : '—'}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="relative flex h-full flex-col overflow-hidden border-t-2 border-t-primary/40 shadow-[0_18px_55px_rgba(0,0,0,0.2),inset_0_1px_0_rgba(var(--primary-rgb),0.06)]">
            <CardHeader className="border-b border-border/70 px-5 py-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="font-semibold tracking-tight">Indexed contexts</h2>
                  <p className="mt-1 text-xs text-muted-foreground">Repositories available to code intelligence</p>
                </div>
                <Link href="/projects" className="group flex items-center gap-1 text-xs font-medium text-primary hover:text-primary-highlight">
                  Manage <ChevronRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
                </Link>
              </div>
            </CardHeader>
            <CardContent className="relative flex-1 p-3">
              {overview.graph.projects.length <= 2 && <SparseTelemetryField />}
              {overview.graph.projects.length === 0 ? (
                <div className="relative z-10 flex h-full min-h-64 items-start justify-center pt-12 text-sm text-muted-foreground">No indexed projects</div>
              ) : (
                <div className="relative z-10 space-y-2">
                  {overview.graph.projects.map((project) => (
                    <Link key={project.name} href="/projects" className="group flex items-center gap-3 rounded-lg border border-border/75 bg-[#080f1a]/70 p-3 transition-[border-color,background-color,transform] hover:-translate-y-px hover:border-primary/25 hover:bg-primary/[0.035]">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-primary/20 bg-primary/[0.06] text-primary">
                        <HardDrive className="h-4 w-4" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-mono text-xs font-medium">{project.name}</div>
                        <div className="mt-1 truncate text-[11px] text-muted-foreground">{project.root_path}</div>
                      </div>
                      <div className="grid shrink-0 grid-cols-2 gap-4 border-l border-border/70 pl-4 text-right">
                        <div><div className="font-mono text-xs text-foreground">{project.nodes.toLocaleString()}</div><div className="text-[9px] uppercase tracking-wider text-muted-foreground">nodes</div></div>
                        <div><div className="font-mono text-xs text-foreground">{project.edges.toLocaleString()}</div><div className="text-[9px] uppercase tracking-wider text-muted-foreground">edges</div></div>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </section>

        <footer className="flex items-center justify-between border-t border-border/70 pt-4 text-[11px] text-muted-foreground">
          <div className="flex items-center gap-5">
            <span className="flex items-center gap-1.5"><Cpu className="h-3.5 w-3.5" /> Runtime <span className="font-mono uppercase text-foreground/75">{overview.runtime_mode}</span></span>
            <span className="flex items-center gap-1.5"><GitBranch className="h-3.5 w-3.5" /> Local-first</span>
          </div>
          <div className={cn('flex items-center gap-2 rounded-lg border px-3 py-1.5 font-mono text-[11px] font-semibold uppercase tracking-[0.08em]', reachable ? 'border-emerald-400/20 bg-emerald-400/[0.06] text-emerald-300' : 'border-destructive/30 bg-destructive/[0.06] text-red-300')}>
            <span className={cn('h-1.5 w-1.5 rounded-full', reachable ? 'status-pulse bg-emerald-400' : 'bg-destructive')} />
            MCP {reachable ? 'online' : 'offline'}
            {overview.mcp_status?.version && <span className="opacity-70">· v{overview.mcp_status.version}</span>}
          </div>
        </footer>
      </div>
    </div>
  );
}
