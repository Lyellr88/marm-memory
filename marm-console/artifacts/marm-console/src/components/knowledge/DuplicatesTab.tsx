import { useState, useEffect, useRef } from 'react';
import { useConceptDuplicates } from '@/hooks/use-marm-queries';
import { Card, CardHeader, CardTitle, CardDescription, Button, Badge, Table, TableHeader, TableRow, TableHead, TableBody, TableCell } from '@/components/ui/core';
import { Eye, ChevronLeft, ChevronRight } from 'lucide-react';
import type { DuplicateCandidate } from '@/lib/marm-types';
import { DuplicateReviewDialog } from './DuplicateReviewDialog';

export function DuplicatesTab() {
  const pageSize = 100;
  const [page, setPage] = useState(0);
  const { data, isLoading, isFetching } = useConceptDuplicates({ offset: page * pageSize, limit: pageSize });
  const [selected, setSelected] = useState<DuplicateCandidate | null>(null);
  const tableScrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!data || page === 0 || page * pageSize < data.total) return;
    setPage(Math.max(0, Math.ceil(data.total / pageSize) - 1));
  }, [data, page]);

  const changePage = (nextPage: number) => {
    setPage(nextPage);
    if (tableScrollRef.current) tableScrollRef.current.scrollTop = 0;
  };

  const rangeStart = data && data.total > 0 ? data.offset + 1 : 0;
  const rangeEnd = data ? data.offset + data.items.length : 0;

  return (
    <div className="h-full flex flex-col pb-4">
      <Card className="flex-1 flex flex-col overflow-hidden">
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div className="space-y-1.5">
            <CardTitle>Potential Duplicates</CardTitle>
            <CardDescription>Compare similar concepts, merge true duplicates, or teach future builds to keep them separate.</CardDescription>
          </div>
          <div className="flex shrink-0 flex-wrap justify-end gap-2">
            <Badge variant="outline" className="font-mono">
              {data?.total ?? 0} found
            </Badge>
            <Badge variant="outline" className="font-mono text-amber-500">
              ≥{Math.round((data?.threshold ?? 0.88) * 100)}% similarity
            </Badge>
          </div>
        </CardHeader>
        <div ref={tableScrollRef} className="flex-1 overflow-auto p-0">
          <Table>
            <TableHeader className="sticky top-0 bg-muted/80 backdrop-blur">
              <TableRow>
                <TableHead>Entity A</TableHead>
                <TableHead>Entity B</TableHead>
                <TableHead className="text-right">Similarity</TableHead>
                <TableHead className="w-28 text-right">Review</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {isLoading ? (
                <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground h-24">Loading duplicates...</TableCell></TableRow>
              ) : data?.items.length === 0 ? (
                <TableRow><TableCell colSpan={4} className="text-center text-muted-foreground h-24">No duplicate candidates found.</TableCell></TableRow>
              ) : (
                data?.items.map((dup) => (
                  <TableRow key={`${dup.entity_a.id}:${dup.entity_b.id}`}>
                    <TableCell>
                      <div className="font-mono text-sm">{dup.entity_a.name}</div>
                      <Badge variant="outline" className="text-[10px] mt-1">{dup.entity_a.type}</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="font-mono text-sm">{dup.entity_b.name}</div>
                      <Badge variant="outline" className="text-[10px] mt-1">{dup.entity_b.type}</Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <span className="font-mono text-sm text-amber-500">{(dup.similarity * 100).toFixed(1)}%</span>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="outline" size="sm" onClick={() => setSelected(dup)}>
                        <Eye className="mr-2 h-3.5 w-3.5" /> Review
                      </Button>
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
        {data && (
          <div className="flex flex-col gap-3 border-t border-border/70 px-4 py-3 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <span>
              Showing pairs {rangeStart}–{rangeEnd} of {data.total} from {data.scanned_entities} embedded concepts
              {data.scanned_entities === data.scan_limit ? ` (scan capped at ${data.scan_limit})` : ''}.
            </span>
            <div className="flex shrink-0 items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page === 0 || isFetching}
                onClick={() => changePage(page - 1)}
                aria-label="Previous duplicate pairs"
              >
                <ChevronLeft className="mr-1 h-4 w-4" /> Previous
              </Button>
              <span className="min-w-16 text-center font-mono text-foreground">
                Page {Math.floor(data.offset / data.result_limit) + 1}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={!data.has_more || isFetching}
                onClick={() => changePage(page + 1)}
                aria-label="Next duplicate pairs"
              >
                Next <ChevronRight className="ml-1 h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </Card>
      <DuplicateReviewDialog candidate={selected} onOpenChange={(open) => !open && setSelected(null)} />
    </div>
  );
}
