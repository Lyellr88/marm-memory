import { Cpu } from 'lucide-react';
import { cn } from '@/components/ui/core';
import type { GpuInfo, HardwareStatus } from '@/lib/marm-types';

/** Megabytes as something a person reads, with the unit the size deserves.
 *
 *  Model weights are talked about in GB and VRAM headroom in GB, so a bar
 *  reading "3879 MB free of 24576 MB" makes the reader do the division that
 *  decides whether a 16 GB model fits.
 */
export function formatMb(mb: number | null | undefined): string {
  if (mb === null || mb === undefined) return '—';
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${mb.toLocaleString()} MB`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(0)} MB`;
  return `${bytes.toLocaleString()} B`;
}

/** How full the card is, and how alarming that is.
 *
 *  The thresholds are about whether another model would fit, not about
 *  health: a GPU at 85% is doing its job, it just has no room left for the
 *  thing the reader is about to try to load.
 */
function usageTone(used: number, total: number): string {
  const ratio = used / total;
  if (ratio >= 0.9) return 'bg-destructive';
  if (ratio >= 0.7) return 'bg-amber-400';
  return 'bg-emerald-400';
}

export function GpuCard({ gpu, compact = false }: { gpu: GpuInfo; compact?: boolean }) {
  const total = gpu.memory_total_mb;
  const used = gpu.memory_used_mb;
  const free = gpu.memory_free_mb;
  const hasSplit = total !== null && used !== null;

  return (
    <div
      className={cn(
        'rounded-xl border border-border/70 bg-card/45 p-3',
        compact && 'p-2.5',
      )}
    >
      <div className="flex items-start gap-2">
        <Cpu className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="truncate text-sm font-semibold" title={gpu.name}>
              {gpu.name}
            </span>
            <span className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
              {gpu.vendor}
            </span>
          </div>

          {/* Apple Silicon has no dedicated VRAM to split, so it gets a
              sentence rather than a bar pretending to measure one. */}
          {gpu.unified ? (
            <p className="mt-1 text-[11px] text-muted-foreground">
              {total !== null ? `${formatMb(total)} unified memory` : 'Unified memory'} —
              shared with the system, so there is no separate VRAM figure.
            </p>
          ) : hasSplit ? (
            <>
              <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-background/60">
                <div
                  className={cn('h-full rounded-full transition-all', usageTone(used, total))}
                  style={{ width: `${Math.min(100, (used / total) * 100)}%` }}
                />
              </div>
              <div className="mt-1.5 flex flex-wrap gap-x-3 text-[11px] tabular-nums text-muted-foreground">
                <span>
                  <strong className="font-semibold text-foreground/90">{formatMb(free)}</strong> free
                </span>
                <span>{formatMb(used)} used</span>
                <span>{formatMb(total)} total</span>
                {gpu.utilisation_percent !== null && <span>{gpu.utilisation_percent}% busy</span>}
              </div>
            </>
          ) : (
            <p className="mt-1 text-[11px] text-muted-foreground">
              Present, but this vendor exposes no memory counter MARM can read.
            </p>
          )}

          {!compact && gpu.driver && (
            <p className="mt-1 font-mono text-[10px] text-muted-foreground">driver {gpu.driver}</p>
          )}
        </div>
      </div>
    </div>
  );
}

export function GpuList({ hardware, compact }: { hardware?: HardwareStatus; compact?: boolean }) {
  if (!hardware || !hardware.detected) {
    return (
      <p className="text-[11px] text-muted-foreground">
        No GPU was detected on this {hardware?.platform ?? 'machine'}. A local model still runs on
        the CPU — slower, but nothing here depends on an accelerator.
      </p>
    );
  }
  return (
    <div className={cn('grid gap-2', hardware.gpus.length > 1 && 'sm:grid-cols-2')}>
      {hardware.gpus.map((gpu) => (
        <GpuCard key={`${gpu.vendor}-${gpu.index}`} gpu={gpu} compact={compact} />
      ))}
    </div>
  );
}
