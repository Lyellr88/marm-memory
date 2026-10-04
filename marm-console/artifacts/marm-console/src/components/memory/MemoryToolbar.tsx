import { Button, Input, Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/core';
import { Search, Trash2, Plus } from 'lucide-react';
import type { Filters, MemoryListParams } from '@/lib/marm-types';

/** Sentinel for "load every project's memories".
 *
 *  Radix forbids `value=""`, and the option needs to be explicit rather than
 *  the default: one project is a bounded page of rows, every project is the
 *  whole store, and the store is the thing that grows. */
const ALL_PROJECTS = '__all__';

type MemoryToolbarProps = {
  params: MemoryListParams;
  filters: Filters | undefined;
  selectedCount: number;
  bulkPending: boolean;
  updateFilters: (updates: Partial<MemoryListParams>) => void;
  setScopedAll: (scopedAll: boolean) => void;
  onBulkDelete: () => void;
  onNew: () => void;
};

export function MemoryToolbar({ params, filters, selectedCount, bulkPending, updateFilters, setScopedAll, onBulkDelete, onNew }: MemoryToolbarProps) {
  return (
    <div className="flex shrink-0 items-center gap-3 rounded-xl border border-card-border bg-card/70 p-2 shadow-[0_12px_34px_rgba(0,0,0,0.14)]">
      <div className="relative flex-1">
        <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input 
          placeholder="Search memories..." 
          className="border-transparent bg-background/65 pl-9 hover:border-primary/25"
          value={params.q || ''}
          onChange={e => updateFilters({ q: e.target.value || undefined })}
        />
      </div>
      <Select
        value={params.project || ALL_PROJECTS}
        onValueChange={v => {
          setScopedAll(v === ALL_PROJECTS);
          updateFilters({ project: v === ALL_PROJECTS ? undefined : v });
        }}
      >
        <SelectTrigger className="w-[210px] border-transparent bg-background/65" aria-label="Project scope">
          <SelectValue placeholder="Project" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL_PROJECTS}>All projects (slower)</SelectItem>
          {filters?.projects.map(p => <SelectItem key={p} value={p}>{p}</SelectItem>)}
        </SelectContent>
      </Select>
      <Select value={params.session || "all"} onValueChange={v => updateFilters({ session: v === "all" ? undefined : v })}>
        <SelectTrigger className="w-[180px] border-transparent bg-background/65">
          <SelectValue placeholder="Session" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All Sessions</SelectItem>
          {filters?.sessions.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
        </SelectContent>
      </Select>
      <Select value={params.compaction_role || "all"} onValueChange={v => updateFilters({ compaction_role: v === "all" ? undefined : v as any })}>
        <SelectTrigger className="w-[180px] border-transparent bg-background/65">
          <SelectValue placeholder="Compaction Role" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">Any Role</SelectItem>
          <SelectItem value="none">None</SelectItem>
          <SelectItem value="source">Source</SelectItem>
          <SelectItem value="summary">Summary</SelectItem>
          <SelectItem value="compacted">Compacted (Virtual)</SelectItem>
        </SelectContent>
      </Select>
      {selectedCount > 0 ? (
        <Button className="bulk-action-enter" variant="destructive" onClick={onBulkDelete} isLoading={bulkPending}>
          <Trash2 className="w-4 h-4 mr-2" /> Delete {selectedCount}
        </Button>
      ) : (
        <Button onClick={onNew}>
          <Plus className="w-4 h-4 mr-2" /> New
        </Button>
      )}
    </div>
  );
}
