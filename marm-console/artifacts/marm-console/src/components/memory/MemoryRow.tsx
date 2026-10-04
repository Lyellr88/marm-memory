import { format } from 'date-fns';
import { decodeEntities } from '@/lib/entities';
import { Badge, TableRow, TableCell, cn } from '@/components/ui/core';
import type { Memory, MemoryId } from '@/lib/marm-types';
import { memoryContext } from './shared';

export function MemoryRow({ 
  memory, 
  onSelect,
  selected,
  fresh,
  onToggleSelect 
}: { 
  memory: Memory, 
  onSelect: (m: Memory) => void,
  selected: boolean,
  fresh: boolean,
  onToggleSelect: (id: MemoryId) => void
}) {
  const context = memoryContext(memory.context_type);
  const ContextIcon = context.icon;
  return (
    <TableRow
      className={cn(
        'group cursor-pointer border-l-2 transition-[background-color,border-color,box-shadow] duration-200 hover:bg-primary/[0.045] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
        context.rail,
        selected && 'bg-primary/[0.065] shadow-[inset_3px_0_0_rgba(var(--primary-rgb),0.75)]',
        fresh && 'memory-new',
      )}
      onClick={() => onSelect(memory)}
      tabIndex={0}
      onKeyDown={(event) => {
        if (event.currentTarget !== event.target) return;
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelect(memory);
        }
      }}
    >
      <TableCell className="w-[40px] pl-4" onClick={(e) => e.stopPropagation()}>
        <input 
          type="checkbox" 
          checked={selected}
          onChange={() => onToggleSelect(memory.id)}
          aria-label={`Select memory ${memory.id}`}
          className="rounded border-input bg-background"
        />
      </TableCell>
      <TableCell className="w-[100px] font-mono text-xs text-muted-foreground">{format(new Date(memory.created_at), 'MMM d, HH:mm')}</TableCell>
      <TableCell>
        <div className="flex gap-2 mb-1">
          <Badge variant="outline" className="text-[10px] py-0">{memory.session_name}</Badge>
          {memory.project && <Badge variant="secondary" className="text-[10px] py-0">{memory.project}</Badge>}
          <Badge variant="outline" className={cn('gap-1 text-[10px] py-0', context.tone)}>
            <ContextIcon className="h-2.5 w-2.5" /> {memory.context_type || 'general'}
          </Badge>
        </div>
        <div className="line-clamp-2 text-sm leading-relaxed text-foreground/90 transition-colors group-hover:text-foreground">{decodeEntities(memory.content)}</div>
      </TableCell>
      <TableCell className="text-right">
        {memory.compaction_role !== 'none' && (
          <Badge variant={memory.compaction_role === 'summary' ? 'default' : 'outline'} className="text-[10px]">
            {memory.compaction_role}
          </Badge>
        )}
      </TableCell>
    </TableRow>
  );
}
