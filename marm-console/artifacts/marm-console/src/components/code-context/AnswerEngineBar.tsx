import { Link } from 'wouter';
import { Cpu, Settings2, Sparkles, ZapOff } from 'lucide-react';
import { cn } from '@/components/ui/core';
import { formatMb } from '@/components/system/gpu';
import type { HardwareStatus, LocalLlmStatus } from '@/lib/marm-types';

/** What will answer an Ask, on what hardware, before anyone asks.
 *
 *  WHY THIS IS ON THIS PAGE AND NOT ONLY IN SETTINGS
 *      "Ask" is the one control here that sends work to a model, and until
 *      now the page said nothing about which model, or whether one was
 *      reachable at all. A reader whose answer came back slow, or stale, or
 *      not at all, had no way to tell from this screen whether they were
 *      talking to a 27B on a 3090 or to nothing. The bar is one line and it
 *      states the two facts that explain the answer they are about to get.
 *
 *  WHY IT SHOWS THE MODEL EVEN WHEN GENERATION IS SWITCHED OFF
 *      Off is a state someone chose and may want to undo from here, so the
 *      bar names what would answer and links to where the switch lives.
 *      Rendering nothing would make a deliberate setting look like a broken
 *      page.
 */
export function AnswerEngineBar({
  llm,
  hardware,
  className,
}: {
  llm?: LocalLlmStatus;
  hardware?: HardwareStatus;
  className?: string;
}) {
  // No endpoint configured at all is a different thing from one that is off
  // or unreachable, and it is the only case where this bar has nothing
  // useful to say -- there is no model, no setting, and nothing to fix here.
  if (!llm || !llm.configured) return null;

  const gpu = hardware?.gpus?.[0];
  const off = !llm.enabled;
  const unreachable = llm.enabled && !llm.available;
  const model = llm.model_in_use ?? llm.model;

  return (
    <section
      className={cn(
        'flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border px-4 py-2.5 text-[11px]',
        off || unreachable
          ? 'border-amber-500/25 bg-amber-500/[0.05]'
          : 'border-card-border bg-card/40',
        className,
      )}
      aria-label="What answers an Ask"
    >
      <span className="flex items-center gap-2 font-semibold uppercase tracking-[0.14em] text-rose-300/90">
        {off || unreachable ? (
          <ZapOff className="h-3 w-3" />
        ) : (
          <Sparkles className="h-3 w-3" />
        )}
        Ask runs on
      </span>

      {off ? (
        <span className="text-amber-200">
          Generation is switched off. Everything else on this page still works — only the
          answer needs a model.
        </span>
      ) : unreachable ? (
        <span className="text-amber-200">
          No model answered at{' '}
          <code className="font-mono text-[10px]">{llm.endpoint}</code>. Ranking, source and
          memory are unaffected.
        </span>
      ) : (
        <>
          <span className="flex items-center gap-1.5">
            <code className="rounded bg-muted/50 px-1.5 py-0.5 font-mono text-[10px] text-foreground/90">
              {model}
            </code>
            {llm.runtime && <span className="text-muted-foreground">via {llm.runtime}</span>}
            {llm.context_length && (
              <span className="text-muted-foreground tabular-nums">
                · {(llm.context_length / 1024).toFixed(0)}K context
              </span>
            )}
          </span>
          {gpu && (
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <Cpu className="h-3 w-3 text-emerald-400" />
              <span className="truncate" title={gpu.name}>
                {gpu.name}
              </span>
              {/* Free VRAM is the number that predicts whether the next model
                  a reader picks will load, so it is the one shown here. On
                  unified memory there is no such split -- see GpuCard. */}
              {!gpu.unified && gpu.memory_free_mb !== null && (
                <span className="tabular-nums">
                  · {formatMb(gpu.memory_free_mb)} free of {formatMb(gpu.memory_total_mb)}
                </span>
              )}
              {gpu.unified && gpu.memory_total_mb !== null && (
                <span className="tabular-nums">· {formatMb(gpu.memory_total_mb)} unified</span>
              )}
            </span>
          )}
        </>
      )}

      <Link
        href="/system?tab=controls"
        className="ml-auto flex items-center gap-1.5 rounded-lg border border-border/70 px-2 py-1 text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
        title="Change the model, turn generation on or off, and see every model on this machine"
      >
        <Settings2 className="h-3 w-3" />
        Model settings in System
      </Link>
    </section>
  );
}
