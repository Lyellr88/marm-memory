import { useState } from 'react';
import { useSummary, useSessions, useCreateSession, useDeleteSession, useDeleteAllSessions, useLogs, useFilters, useDeleteLog, useDeleteAllLogs } from '@/hooks/use-marm-queries';
import { Card, CardContent, CardHeader, CardTitle, CardDescription, Badge, Button, Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, Select, SelectTrigger, SelectValue, SelectContent, SelectItem, Table, TableHeader, TableRow, TableHead, TableBody, TableCell, Input } from '@/components/ui/core';
import { format } from 'date-fns';
import { RefreshCw, Eye, Trash2, Plus, Search } from 'lucide-react';
import type { LogListParams } from '@/lib/marm-types';
import { type ActionNotice, mutationErrorMessage, ActionNoticePanel } from './shared';

function SessionSummaryDialog({ session, open, onOpenChange }: { session: string | null, open: boolean, onOpenChange: (o: boolean) => void }) {
  const { data, isLoading, isFetching, refetch } = useSummary(session || '');

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
        <DialogHeader>
          <DialogTitle className="font-mono">{session}</DialogTitle>
          <DialogDescription>Rolling session summary maintained by the MARM server.</DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <div className="p-8 text-center text-muted-foreground">Loading summary...</div>
        ) : (
          <div className="flex-1 overflow-auto space-y-4">
            <div className="flex items-center gap-2 flex-wrap">
              <Badge variant={data?.is_dirty ? 'secondary' : 'default'} className="text-[10px] uppercase">
                {data?.is_dirty ? 'Stale — recompute pending' : 'Fresh'}
              </Badge>
              <span className="text-xs text-muted-foreground">{data?.entry_count} entries summarized</span>
              {data?.generated_at && (
                <span className="text-xs text-muted-foreground">· generated {format(new Date(data.generated_at), 'MMM d, HH:mm')}</span>
              )}
            </div>
            <div className="p-4 bg-muted/30 rounded-md text-sm whitespace-pre-wrap font-mono">
              {data?.summary || 'No summary generated yet.'}
            </div>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
          <Button onClick={() => refetch()} isLoading={isFetching}>
            <RefreshCw className="w-4 h-4 mr-2" /> Regenerate
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function SessionsTab() {
  const { data, isLoading } = useSessions();
  const [summarySession, setSummarySession] = useState<string | null>(null);
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const createSession = useCreateSession();
  const deleteSession = useDeleteSession();
  const deleteAllSessions = useDeleteAllSessions();

  const handleCreateSession = () => {
    const name = prompt('Session name');
    if (!name?.trim()) return;
    createSession.mutate(name.trim(), {
      onSuccess: () => setActionNotice({ kind: 'success', message: `Session '${name.trim()}' created.` }),
    });
  };

  const handleDeleteSession = (name: string) => {
    const typed = prompt(`Type DELETE to delete session '${name}' and its log-backed memories.`);
    if (typed !== 'DELETE') return;
    deleteSession.mutate(name, {
      onSuccess: (result) => {
        setActionNotice({
          kind: 'success',
          message: `Session '${name}' deleted. ${result.deleted_count} log entries and ${result.memories_deleted} semantic log memories removed.`,
        });
      },
    });
  };

  const handleDeleteAllSessions = () => {
    const typed = prompt('Type DELETE_ALL to delete every session and its log-backed memories.');
    if (typed !== 'DELETE_ALL') return;
    deleteAllSessions.mutate(undefined, {
      onSuccess: (result) => {
        const failed = result.failed_sessions?.length ?? 0;
        setActionNotice({
          kind: failed ? 'error' : 'success',
          message: failed
            ? `${result.deleted_sessions} sessions deleted, ${failed} failed. ${result.deleted_count} log entries and ${result.memories_deleted} semantic log memories removed.`
            : `${result.deleted_sessions} sessions deleted. ${result.deleted_count} log entries and ${result.memories_deleted} semantic log memories removed.`,
        });
      },
    });
  };
  
  if (isLoading) return <div className="p-8 text-center text-muted-foreground">Loading sessions...</div>;

  return (
    <div className="h-full overflow-auto pb-4 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <ActionNoticePanel
          notice={
            createSession.error
              ? { kind: 'error', message: mutationErrorMessage(createSession.error) }
              : deleteSession.error
                ? { kind: 'error', message: mutationErrorMessage(deleteSession.error) }
                : deleteAllSessions.error
                  ? { kind: 'error', message: mutationErrorMessage(deleteAllSessions.error) }
                : actionNotice
          }
        />
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            className="text-destructive hover:text-destructive"
            onClick={handleDeleteAllSessions}
            isLoading={deleteAllSessions.isPending}
          >
            <Trash2 className="w-4 h-4 mr-2" /> Delete All
          </Button>
          <Button size="sm" onClick={handleCreateSession} isLoading={createSession.isPending}>
            <Plus className="w-4 h-4 mr-2" /> New Session
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 content-start">
        {data?.map(session => (
          <Card key={session.name} className={session.active ? 'border-primary' : ''}>
          <CardHeader className="pb-2">
            <div className="flex justify-between items-start">
              <CardTitle className="font-mono text-base">{session.name}</CardTitle>
              {session.active && <Badge className="text-[10px]">Active</Badge>}
            </div>
            <CardDescription className="text-xs">
              Last active: {format(new Date(session.last_accessed_at), 'MMM d, HH:mm')}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-2 text-sm mt-2">
              <div className="p-2 bg-muted/30 rounded flex flex-col items-center justify-center">
                <span className="text-xl font-bold">{session.memory_count}</span>
                <span className="text-xs text-muted-foreground">Memories</span>
              </div>
              <div className="p-2 bg-muted/30 rounded flex flex-col items-center justify-center">
                <span className="text-xl font-bold">{session.compaction_count}</span>
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
            <div className="grid grid-cols-2 gap-2 mt-4">
              <Button variant="outline" size="sm" onClick={() => setSummarySession(session.name)}>
                <Eye className="w-4 h-4 mr-2" /> Summary
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive"
                onClick={() => handleDeleteSession(session.name)}
                isLoading={deleteSession.isPending}
              >
                <Trash2 className="w-4 h-4 mr-2" /> Delete
              </Button>
            </div>
          </CardContent>
          </Card>
        ))}
      </div>
      <SessionSummaryDialog session={summarySession} open={!!summarySession} onOpenChange={(o) => !o && setSummarySession(null)} />
    </div>
  );
}

export function LogsTab() {
  const [params, setParams] = useState<LogListParams>({ limit: 50 });
  const { data, isLoading } = useLogs(params);
  const { data: filters } = useFilters();
  const [actionNotice, setActionNotice] = useState<ActionNotice | null>(null);
  const deleteLog = useDeleteLog();
  const deleteAllLogs = useDeleteAllLogs();

  const handleDeleteLog = (id: number, sessionName: string) => {
    const typed = prompt(`Type DELETE to delete log entry ${id}.`);
    if (typed !== 'DELETE') return;
    deleteLog.mutate({ id, sessionName }, {
      onSuccess: (result) => {
        setActionNotice({
          kind: 'success',
          message: `Log ${result.log_id} deleted. ${result.memories_deleted} semantic log memories removed.`,
        });
      },
    });
  };

  const handleDeleteAllLogs = () => {
    const typed = prompt('Type DELETE_ALL to delete every log entry.');
    if (typed !== 'DELETE_ALL') return;
    deleteAllLogs.mutate(undefined, {
      onSuccess: (result) => {
        setActionNotice({
          kind: 'success',
          message: `${result.deleted_count} log entries deleted. ${result.memories_deleted} semantic log memories removed.`,
        });
      },
    });
  };

  return (
    <div className="space-y-4 h-full flex flex-col">
      <ActionNoticePanel
        notice={
          deleteLog.error
            ? { kind: 'error', message: mutationErrorMessage(deleteLog.error) }
            : deleteAllLogs.error
              ? { kind: 'error', message: mutationErrorMessage(deleteAllLogs.error) }
              : actionNotice
        }
      />
      <div className="flex gap-4 items-center shrink-0">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input 
            placeholder="Search logs..." 
            className="pl-9 bg-background"
            value={params.q || ''}
            onChange={e => setParams(p => ({ ...p, q: e.target.value || undefined }))}
          />
        </div>
        <Select value={params.session || "all"} onValueChange={v => setParams(p => ({ ...p, session: v === "all" ? undefined : v }))}>
          <SelectTrigger className="w-[180px] bg-background">
            <SelectValue placeholder="Session" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Sessions</SelectItem>
            {filters?.sessions.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          className="text-destructive hover:text-destructive"
          onClick={handleDeleteAllLogs}
          isLoading={deleteAllLogs.isPending}
        >
          <Trash2 className="w-4 h-4 mr-2" /> Delete All
        </Button>
      </div>

      <div className="border rounded-md bg-card flex-1 overflow-auto">
        <Table>
          <TableHeader className="sticky top-0 z-10 bg-muted/80 backdrop-blur">
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Topic / Context</TableHead>
              <TableHead>Summary</TableHead>
              <TableHead className="w-[80px]" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow><TableCell colSpan={4} className="h-24 text-center text-muted-foreground">Loading logs...</TableCell></TableRow>
            ) : data?.length === 0 ? (
              <TableRow><TableCell colSpan={4} className="h-24 text-center text-muted-foreground">No logs found</TableCell></TableRow>
            ) : (
              data?.map(l => (
                <TableRow key={l.id}>
                  <TableCell className="w-[100px] font-mono text-xs text-muted-foreground">{format(new Date(l.date), 'MMM d, HH:mm')}</TableCell>
                  <TableCell>
                    <div className="flex gap-2 mb-1">
                      <Badge variant="outline" className="text-[10px] py-0">{l.session_name}</Badge>
                      {l.topic && <Badge variant="secondary" className="text-[10px] py-0">{l.topic}</Badge>}
                    </div>
                  </TableCell>
                  <TableCell className="text-sm line-clamp-2">{l.summary || l.entry}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      onClick={() => handleDeleteLog(l.id, l.session_name)}
                      isLoading={deleteLog.isPending}
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
