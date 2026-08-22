import { useEffect, useState } from 'react';
import { useSummary, useGenerateSummary, useSessions, useCreateSession, useBulkDeleteSessions, useLogs, useFilters, useBulkDeleteLogs } from '@/hooks/use-marm-queries';
import { Card, CardContent, CardHeader, CardTitle, CardDescription, Badge, Button, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, Select, SelectTrigger, SelectValue, SelectContent, SelectItem, Table, TableHeader, TableRow, TableHead, TableBody, TableCell, Input, cn } from '@/components/ui/core';
import { format } from 'date-fns';
import { RefreshCw, Eye, Trash2, Plus, Search } from 'lucide-react';
import type { LogListParams } from '@/lib/marm-types';
import { type ActionNotice, mutationErrorMessage, ActionNoticePanel, DeleteSelectionDialog, MemoryEmptyState, PageControls } from './shared';

const SESSION_PAGE_SIZE = 15;
const LOG_PAGE_SIZE = 100;

function SessionSummaryDialog({ session, open, onOpenChange }: { session: string | null, open: boolean, onOpenChange: (o: boolean) => void }) {
  const { data, isLoading, isError, error } = useSummary(session || '');
  const generateSummary = useGenerateSummary();
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);

  useEffect(() => {
    setActionNotice(null);
  }, [open, session]);

  const handleGenerate = () => {
    if (!session) return;
    setActionNotice(null);
    generateSummary.mutate(session, {
      onSuccess: (result) => {
        if (result.status === 'empty') {
          setActionNotice({
            kind: 'warning',
            message: result.message || 'This session has no structured logs to summarize.',
          });
          return;
        }
        setActionNotice({
          kind: 'success',
          message: data?.summary ? 'Session summary refreshed.' : 'Session summary generated.',
        });
      },
      onError: (generateError) => {
        setActionNotice({ kind: 'error', message: mutationErrorMessage(generateError) });
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="font-mono">{session}</DialogTitle>
          <DialogDescription>Rolling session summary maintained by the MARM server.</DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <div className="p-8 text-center text-muted-foreground">Loading summary...</div>
        ) : isError ? (
          <ActionNoticePanel notice={{ kind: 'error', message: mutationErrorMessage(error) }} />
        ) : (
          <div aria-busy={generateSummary.isPending} className={cn('relative flex-1 overflow-auto space-y-4', generateSummary.isPending && 'summary-scanning')}>
            {data?.summary ? (
              <>
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant={data.is_dirty ? 'secondary' : 'default'} className="text-[10px] uppercase">
                    {data.is_dirty ? 'Stale — refresh available' : 'Fresh'}
                  </Badge>
                  <span className="text-xs text-muted-foreground">{data.entry_count} entries summarized</span>
                  {data.generated_at && (
                    <span className="text-xs text-muted-foreground">· generated {format(new Date(data.generated_at), 'MMM d, HH:mm')}</span>
                  )}
                </div>
                <div className="p-4 bg-muted/30 rounded-md text-sm whitespace-pre-wrap font-mono">
                  {data.summary}
                </div>
              </>
            ) : (
              <div className="rounded-xl border border-dashed border-border bg-muted/20 p-8 text-center">
                <p className="text-sm font-medium">No summary cached yet</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Generate one from this session&apos;s structured logs.
                </p>
              </div>
            )}
            <ActionNoticePanel notice={actionNotice} />
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          <Button onClick={handleGenerate} isLoading={generateSummary.isPending} disabled={!session || isLoading}>
            <RefreshCw className="w-4 h-4 mr-2" /> {data?.summary ? 'Refresh Summary' : 'Generate Summary'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function SessionsTab() {
  const { data, isLoading } = useSessions();
  const [page, setPage] = useState(0);
  const [summarySession, setSummarySession] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [selectedNames, setSelectedNames] = useState<Set<string>>(new Set());
  const [deleteOpen, setDeleteOpen] = useState(false);
  const createSession = useCreateSession();
  const bulkDelete = useBulkDeleteSessions();

  const total = data?.length ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / SESSION_PAGE_SIZE));
  const visibleSessions = data?.slice(page * SESSION_PAGE_SIZE, (page + 1) * SESSION_PAGE_SIZE) ?? [];

  useEffect(() => {
    if (page >= pageCount) setPage(pageCount - 1);
  }, [page, pageCount]);

  useEffect(() => {
    const visibleNames = new Set(visibleSessions.map((session) => session.name));
    setSelectedNames((previous) => {
      const next = new Set(Array.from(previous).filter((name) => visibleNames.has(name)));
      return next.size === previous.size ? previous : next;
    });
  }, [visibleSessions]);

  const allSelected = !!visibleSessions.length && visibleSessions.every((session) => selectedNames.has(session.name));

  const toggleSession = (name: string) => {
    setSelectedNames((previous) => {
      const next = new Set(previous);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const handleCreateSession = () => {
    const name = prompt('Session name');
    if (!name?.trim()) return;
    createSession.mutate(name.trim(), {
      onSuccess: () => setActionNotice({ kind: 'success', message: `Session '${name.trim()}' created.` }),
      onError: (error) => setActionNotice({ kind: 'error', message: mutationErrorMessage(error) }),
    });
  };

  const confirmDelete = () => {
    const names = Array.from(selectedNames);
    if (!names.length) return;
    bulkDelete.mutate(names, {
      onSuccess: (result) => {
        const failed = result.failed_sessions.length;
        setDeleteOpen(false);
        setSelectedNames(new Set(result.failed_sessions.map((item) => item.session_name)));
        setActionNotice({
          kind: failed ? 'warning' : 'success',
          message: failed
            ? `${result.deleted_sessions} sessions deleted; ${failed} could not be deleted.`
            : `${result.deleted_sessions} sessions deleted with ${result.deleted_count} log entries and ${result.memories_deleted} semantic log memories.`,
        });
      },
      onError: (error) => setActionNotice({ kind: 'error', message: mutationErrorMessage(error) }),
    });
  };
  
  if (isLoading) return <div className="p-8 text-center text-muted-foreground">Loading sessions...</div>;

  return (
    <div className="h-full space-y-4 overflow-auto pb-4">
      <div className="flex items-center justify-between gap-3 rounded-xl border border-card-border bg-card/70 p-2 shadow-[0_12px_34px_rgba(0,0,0,0.14)]">
        <label className="flex cursor-pointer items-center gap-2 px-2 text-xs text-muted-foreground">
          <input
            type="checkbox"
            checked={allSelected}
            onChange={() => setSelectedNames(allSelected ? new Set() : new Set(visibleSessions.map((session) => session.name)))}
            className="rounded border-input bg-background"
          />
          Select all sessions
        </label>
        <div className="flex gap-2">
          {selectedNames.size > 0 ? (
            <Button className="bulk-action-enter" size="sm" variant="destructive" onClick={() => setDeleteOpen(true)}>
              <Trash2 className="w-4 h-4 mr-2" /> Delete {selectedNames.size}
            </Button>
          ) : (
            <Button size="sm" onClick={handleCreateSession} isLoading={createSession.isPending}>
              <Plus className="w-4 h-4 mr-2" /> New Session
            </Button>
          )}
        </div>
      </div>
      <ActionNoticePanel notice={actionNotice} />
      {total ? (
        <div className="grid content-start grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {visibleSessions.map(session => (
          <Card
            key={session.name}
            className={cn(
              'group border-t-2 border-t-border transition-[border-color,transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-[0_20px_50px_rgba(0,0,0,0.24)]',
              session.active && 'border-primary/35 border-t-primary shadow-[inset_0_1px_0_rgba(var(--primary-rgb),0.12)]',
              selectedNames.has(session.name) && 'bg-primary/[0.045] ring-1 ring-primary/25'
            )}
          >
          <CardHeader className="pb-2">
            <div className="flex justify-between items-start">
              <CardTitle className="font-mono text-base">{session.name}</CardTitle>
              <div className="flex items-center gap-2">
                {session.active && <Badge className="text-[10px]">Active</Badge>}
                <input
                  type="checkbox"
                  checked={selectedNames.has(session.name)}
                  onChange={() => toggleSession(session.name)}
                  aria-label={`Select session ${session.name}`}
                  className="rounded border-input bg-background"
                />
              </div>
            </div>
            <CardDescription className="text-xs">
              Last active: {format(new Date(session.last_accessed_at), 'MMM d, HH:mm')}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-2 text-sm mt-2">
              <div className="flex flex-col items-center justify-center rounded-lg border border-border/60 bg-background/45 p-2">
                <span className="font-mono text-xl font-semibold">{session.memory_count}</span>
                <span className="text-xs text-muted-foreground">Memories</span>
              </div>
              <div className="flex flex-col items-center justify-center rounded-lg border border-border/60 bg-background/45 p-2">
                <span className="font-mono text-xl font-semibold">{session.compaction_count}</span>
                <span className="text-xs text-muted-foreground">Compactions</span>
              </div>
            </div>
            {session.projects.length > 0 && (
              <div className="mt-4">
                <div className="text-xs text-muted-foreground mb-1">Projects</div>
                <div className="flex flex-wrap gap-1">
                  {session.projects.map(p => <Badge key={p} variant="secondary" className="text-[10px]">{p}</Badge>)}
                </div>
              </div>
            )}
            <div className="mt-4">
              <Button className="w-full" variant="outline" size="sm" onClick={() => setSummarySession(session.name)}>
                <Eye className="w-4 h-4 mr-2" /> Summary
              </Button>
            </div>
          </CardContent>
          </Card>
          ))}
        </div>
      ) : (
        <MemoryEmptyState title="No sessions yet" detail="Create a session to begin a new context workspace." className="min-h-64 border border-dashed border-primary/15 bg-card/45" />
      )}
      {total > 0 && (
        <PageControls
          page={page}
          pageSize={SESSION_PAGE_SIZE}
          total={total}
          itemLabel="sessions"
          onPageChange={setPage}
        />
      )}
      <SessionSummaryDialog session={summarySession} open={!!summarySession} onOpenChange={(o) => !o && setSummarySession(null)} />
      <DeleteSelectionDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        count={selectedNames.size}
        itemLabel="session"
        description="Deleting a session also removes its structured logs and semantic log memories. Other stored memories are not deleted."
        isPending={bulkDelete.isPending}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

export function LogsTab() {
  const [params, setParams] = useState<LogListParams>({ limit: LOG_PAGE_SIZE, offset: 0 });
  const { data, isLoading, isFetching } = useLogs(params);
  const { data: filters } = useFilters();
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [deleteOpen, setDeleteOpen] = useState(false);
  const bulkDelete = useBulkDeleteLogs();

  useEffect(() => {
    const visibleIds = new Set(data?.items.map((log) => log.id));
    setSelectedIds((previous) => {
      const next = new Set(Array.from(previous).filter((id) => visibleIds.has(id)));
      return next.size === previous.size ? previous : next;
    });
  }, [data?.items]);

  useEffect(() => {
    if (!data || !params.offset || params.offset < data.total) return;
    setParams((previous) => ({
      ...previous,
      offset: Math.max(0, Math.floor((data.total - 1) / LOG_PAGE_SIZE) * LOG_PAGE_SIZE),
    }));
  }, [data, params.offset]);

  const updateFilters = (updates: Partial<LogListParams>) => {
    setParams((previous) => ({ ...previous, ...updates, limit: LOG_PAGE_SIZE, offset: 0 }));
  };

  const currentPage = Math.floor((data?.offset ?? params.offset ?? 0) / LOG_PAGE_SIZE);

  const allSelected = !!data?.items.length && data.items.every((log) => selectedIds.has(log.id));

  const toggleLog = (id: string) => {
    setSelectedIds((previous) => {
      const next = new Set(previous);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const confirmDelete = () => {
    const logs = (data?.items ?? [])
      .filter((log) => selectedIds.has(log.id))
      .map((log) => ({ id: log.id, session_name: log.session_name }));
    if (!logs.length) return;
    bulkDelete.mutate(logs, {
      onSuccess: (result) => {
        const failedIds = new Set(result.failed_logs.map((item) => item.log_id));
        setDeleteOpen(false);
        setSelectedIds(failedIds);
        setActionNotice({
          kind: result.failed_logs.length ? 'warning' : 'success',
          message: result.failed_logs.length
            ? `${result.deleted_count} logs deleted; ${result.failed_logs.length} could not be deleted.`
            : `${result.deleted_count} logs and ${result.memories_deleted} semantic log memories deleted.`,
        });
      },
      onError: (error) => setActionNotice({ kind: 'error', message: mutationErrorMessage(error) }),
    });
  };

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex shrink-0 items-center gap-3 rounded-xl border border-card-border bg-card/70 p-2 shadow-[0_12px_34px_rgba(0,0,0,0.14)]">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input 
            placeholder="Search logs..." 
            className="border-transparent bg-background/65 pl-9 hover:border-primary/25"
            value={params.q || ''}
            onChange={e => updateFilters({ q: e.target.value || undefined })}
          />
        </div>
        <Select value={params.session || "all"} onValueChange={v => updateFilters({ session: v === "all" ? undefined : v })}>
          <SelectTrigger className="w-[180px] border-transparent bg-background/65">
            <SelectValue placeholder="Session" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Sessions</SelectItem>
            {filters?.sessions.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
          </SelectContent>
        </Select>
        {selectedIds.size > 0 && (
          <Button className="bulk-action-enter" variant="destructive" onClick={() => setDeleteOpen(true)}>
            <Trash2 className="w-4 h-4 mr-2" /> Delete {selectedIds.size}
          </Button>
        )}
      </div>
      <ActionNoticePanel notice={actionNotice} />

      <div className="min-h-0 flex flex-1 flex-col overflow-hidden rounded-xl border border-card-border border-t-primary/35 shadow-[0_18px_50px_rgba(0,0,0,0.16)]">
        <div className="min-h-0 flex-1 overflow-auto">
          <Table>
          <TableHeader className="sticky top-0 z-10 bg-card/95 backdrop-blur-xl">
            <TableRow>
              <TableHead className="w-[40px] pl-4">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={() => setSelectedIds(allSelected ? new Set() : new Set(data?.items.map((log) => log.id)))}
                  aria-label="Select all visible logs"
                  className="rounded border-input bg-background"
                />
              </TableHead>
              <TableHead>Time</TableHead>
              <TableHead>Topic / Context</TableHead>
              <TableHead>Summary</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow><TableCell colSpan={4} className="h-24 text-center text-muted-foreground">Loading logs...</TableCell></TableRow>
            ) : data?.items.length === 0 ? (
              <TableRow><TableCell colSpan={4} className="p-4"><MemoryEmptyState title="No logs found" detail="Structured session activity will appear here." /></TableCell></TableRow>
            ) : (
              data?.items.map(l => (
                <TableRow key={l.id} className={cn('transition-colors duration-200', selectedIds.has(l.id) && 'bg-blue-400/[0.055] shadow-[inset_3px_0_0_rgba(96,165,250,0.65)]')}>
                  <TableCell className="w-[40px] pl-4">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(l.id)}
                      onChange={() => toggleLog(l.id)}
                      aria-label={`Select log ${l.id}`}
                      className="rounded border-input bg-background"
                    />
                  </TableCell>
                  <TableCell className="w-[100px] font-mono text-xs text-muted-foreground">{format(new Date(l.date), 'MMM d, HH:mm')}</TableCell>
                  <TableCell>
                    <div className="flex gap-2 mb-1">
                      <Badge variant="outline" className="text-[10px] py-0">{l.session_name}</Badge>
                      {l.topic && <Badge variant="secondary" className="text-[10px] py-0">{l.topic}</Badge>}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm line-clamp-2">{l.summary || l.entry}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
          </Table>
        </div>
        {data && (
          <PageControls
            page={currentPage}
            pageSize={LOG_PAGE_SIZE}
            total={data.total}
            itemLabel="logs"
            isFetching={isFetching}
            onPageChange={(page) => setParams((previous) => ({ ...previous, offset: page * LOG_PAGE_SIZE }))}
          />
        )}
      </div>
      <DeleteSelectionDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        count={selectedIds.size}
        itemLabel="log"
        description="The selected structured logs and their semantic memory copies will be removed permanently."
        isPending={bulkDelete.isPending}
        onConfirm={confirmDelete}
      />
    </div>
  );
}
