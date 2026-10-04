import {
  Button,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  cn,
} from '@/components/ui/core';
import { Panel, SmallStat } from '@/components/ui/panels';
import { Bot, CircleAlert } from 'lucide-react';
import { useLlmModels, useUpdateLlmSettings } from '@/hooks/use-marm-queries';
import { CopyButton } from '@/components/code-context/shared';
import { GpuList } from './gpu';
import { InstalledModels } from './InstalledModels';
import { ServerPicker } from './ServerPicker';
import type { AnalystProfileName, HardwareStatus, LocalLlmStatus } from '@/lib/marm-types';

/** The command that actually changes a llama.cpp model.
 *
 *  Handing the reader the exact invocation is the difference between telling
 *  them MARM cannot switch the model and telling them how to switch it. The
 *  path is the one the runtime reported, which on a container is a path
 *  INSIDE the container -- so the caveat travels with the command rather than
 *  being left for them to discover when it does not exist on the host.
 */
function reloadCommand(path: string | null): string {
  return `llama-server -m ${path ?? '<path to your .gguf>'} -c 65536`;
}

const PROFILE_LABEL: Record<AnalystProfileName, string> = {
  general: 'General — one free-form answer',
  small: 'Small — one narrow operation per call',
  large: 'Large — narrow operations batched in one call',
};

/** The analyst profile. The operator picks it; nothing reads it off the model,
 *  because a model's name says nothing about how it behaves under a budget. */
export function ProfilePicker({ llm }: { llm: LocalLlmStatus }) {
  const update = useUpdateLlmSettings();
  const profile = llm.analyst_profile;
  if (!profile) return null;
  const active = profile.active;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={profile.name}
          onValueChange={(value) => update.mutate({ profile: value as AnalystProfileName })}
        >
          <SelectTrigger aria-label="Analyst profile" className="w-[320px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(Object.keys(PROFILE_LABEL) as AnalystProfileName[]).map((name) => (
              <SelectItem key={name} value={name}>
                {PROFILE_LABEL[name]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {profile.source === 'runtime' && (
          <Button size="sm" variant="outline" onClick={() => update.mutate({ profile: '' })}>
            Use environment
          </Button>
        )}
      </div>
      <p className="font-mono text-[10px] text-muted-foreground">
        {`reads ≤ ${active.context_chars.toLocaleString()} chars · `}
        {`≤ ${active.max_tokens.toLocaleString()} tokens per call`}
        {active.reasoning_tokens > 0 &&
          ` (${active.output_tokens.toLocaleString()} answer + ${active.reasoning_tokens.toLocaleString()} reasoning)`}
        {` · ${active.time_s}s wall time · ${profile.source}`}
      </p>
    </div>
  );
}

/** Whether Guardrails may write without a reviewer. Saved, so it wins over
 *  MARM_ANALYST_AUTO_APPLY; even on, only mechanically provable results apply. */
export function AutoApplyToggle({ llm }: { llm: LocalLlmStatus }) {
  const update = useUpdateLlmSettings();
  const state = llm.analyst_auto_apply;
  if (!state) return null;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4 accent-primary"
            checked={state.enabled}
            disabled={update.isPending}
            onChange={(event) => update.mutate({ auto_apply: event.target.checked })}
          />
          Let Guardrails apply provable results without review
        </label>
        {state.source === 'override' && (
          <Button size="sm" variant="outline" onClick={() => update.mutate({ auto_apply: '' })}>
            Use environment
          </Button>
        )}
      </div>
      {state.source === 'unknown' ? (
        <p className="text-[11px] text-amber-300">
          The saved setting could not be read, so nothing is applied automatically.
        </p>
      ) : (
        <p className="text-[11px] text-muted-foreground">
          Only a call edge, a defined-in range, or a whole verbatim sentence is applied, and every
          decision is recorded on its proposal. Everything else waits for review.{' '}
          <span className="font-mono">{state.source}</span>
        </p>
      )}
    </div>
  );
}

function ModelSwitcher({ llm }: { llm: LocalLlmStatus }) {
  const models = useLlmModels();
  const update = useUpdateLlmSettings();
  const data = models.data;
  const served = data?.served ?? llm.served;
  const canSwitch = data?.can_switch ?? llm.can_switch;

  return (
    <div className="space-y-3">
      {canSwitch ? (
        <div className="flex flex-wrap items-center gap-2">
          <Select
            value={llm.preferred_model ?? llm.model_in_use ?? ''}
            onValueChange={(model) => update.mutate({ model })}
          >
            <SelectTrigger aria-label="Model" className="w-[320px]">
              <SelectValue placeholder="Choose a model" />
            </SelectTrigger>
            <SelectContent>
              {served.map((entry) => (
                <SelectItem key={entry.id ?? ''} value={entry.id ?? ''}>
                  {entry.id}
                  {entry.state ? ` · ${entry.state}` : ''}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {llm.preferred_model && (
            <Button size="sm" variant="outline" onClick={() => update.mutate({ model: '' })}>
              Clear
            </Button>
          )}
        </div>
      ) : (
        /* The measured reason this pane exists. llama.cpp accepts a `model`
           parameter and ignores it, so a dropdown here would report a switch
           that never happened. Saying so, and giving the command that does
           work, is the honest version of the same control. */
        <div className="rounded-lg border border-amber-500/25 bg-amber-500/[0.05] p-3">
          <div className="flex items-start gap-2.5">
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
            <div className="min-w-0 flex-1">
              <p className="text-xs text-amber-100">
                {llm.switch_blocked_reason ??
                  'This runtime does not support choosing a model from here.'}
              </p>
              {llm.runtime === 'llama.cpp' && (
                <div className="mt-2 flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded bg-background/50 px-2 py-1 font-mono text-[10px]">
                    {reloadCommand(llm.model_path)}
                  </code>
                  <CopyButton
                    className="h-6 w-6 shrink-0"
                    value={reloadCommand(llm.model_path)}
                    label="Copy the reload command"
                  />
                </div>
              )}
              {llm.model_path?.startsWith('/models') && (
                <p className="mt-1.5 text-[10px] text-muted-foreground">
                  That path is the one the runtime reported. It is serving from a container, so
                  the file lives elsewhere on this host.
                </p>
              )}
            </div>
          </div>
        </div>
      )}
      {update.data?.llm?.rejected && (
        <p className="text-[11px] text-amber-200">{update.data.llm.rejected}</p>
      )}
    </div>
  );
}

/** Generation on/off, which model answers, and what it runs on. */
export function LocalModelPanels({
  llm,
  hardware,
}: {
  llm?: LocalLlmStatus;
  hardware?: HardwareStatus;
}) {
  const update = useUpdateLlmSettings();

  if (!llm) return null;

  return (
    <div className="space-y-4">
      <Panel
        icon={<Bot className={cn('h-5 w-5', llm.enabled ? 'text-primary' : 'text-amber-400')} />}
        title="Local model"
        description={
          llm.configured ? (
            <>
              Generation is optional everywhere it appears. With it off, Code Context still ranks
              and Distill still selects sentences verbatim — only written answers need a model.{' '}
              {llm.loopback_enforced && (
                <strong className="font-semibold text-foreground/90">
                  Only a loopback endpoint is allowed, so nothing leaves this machine.
                </strong>
              )}
            </>
          ) : (
            <>
              No endpoint is configured. Scan below for a local server, or set{' '}
              <code className="font-mono text-xs">MARM_LLM_URL</code> to one.
            </>
          )
        }
        alert={llm.configured && llm.enabled && !llm.available}
        action={
          llm.configured ? (
            <Button
              size="sm"
              variant={llm.enabled ? 'outline' : 'default'}
              isLoading={update.isPending}
              onClick={() => update.mutate({ enabled: !llm.enabled })}
            >
              {llm.enabled ? 'Turn off' : 'Turn on'}
            </Button>
          ) : undefined
        }
      >
        {llm.configured && (
          <>
            <div className="mt-4 grid gap-3 sm:grid-cols-4">
              <SmallStat
                label="Generation"
                value={llm.enabled ? 'On' : 'Off'}
                tone={llm.enabled ? 'good' : 'warn'}
              />
              <SmallStat
                label="Reachable"
                value={llm.available ? 'Yes' : llm.enabled ? 'No' : 'Not checked'}
                tone={llm.available ? 'good' : llm.enabled ? 'warn' : undefined}
              />
              <SmallStat label="Runtime" value={llm.runtime ?? 'Unknown'} />
              <SmallStat
                label="Context"
                value={llm.context_length ? `${(llm.context_length / 1024).toFixed(0)}K` : '—'}
              />
            </div>

            <div className="mt-3 rounded-lg border border-border/70 bg-background/25 px-3 py-2">
              <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                {/* Off does not mean unknown: the pane you re-enable from has
                    to say what it would re-enable. */}
                {llm.enabled ? 'Answering now' : 'Would answer'}
              </div>
              <code className="mt-1 block break-all font-mono text-xs text-foreground/90">
                {llm.model ?? 'nothing reachable'}
              </code>
              {llm.model_path && (
                <code className="mt-0.5 block break-all font-mono text-[10px] text-muted-foreground">
                  {llm.model_path}
                </code>
              )}
              <div className="mt-1 font-mono text-[10px] text-muted-foreground">{llm.endpoint}</div>
            </div>

            <div className="mt-4 border-t border-border/60 pt-4">
              <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Model
              </div>
              <ModelSwitcher llm={llm} />
            </div>

            <div className="mt-4 border-t border-border/60 pt-4">
              <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                Analyst profile
              </div>
              <ProfilePicker llm={llm} />
            </div>
          </>
        )}

        {/* Also outside the gate: verbatim distill can run Guardrails with no
            model at all. */}
        {llm.analyst_auto_apply && (
          <div className="mt-4 border-t border-border/60 pt-4">
            <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
              Automated Guardrails
            </div>
            <AutoApplyToggle llm={llm} />
          </div>
        )}

        {/* Outside the `configured` gate on purpose: a deployment with no
            endpoint set is precisely the one that needs to find a server. */}
        <div className={cn(llm.configured && 'mt-4 border-t border-border/60 pt-4')}>
          <ServerPicker llm={llm} />
        </div>
      </Panel>

      <Panel
        icon={<Bot className="h-5 w-5 text-emerald-400" />}
        title="Accelerator"
        description={
          <>
            What a local model would run on. Free memory is the figure that decides whether the
            next model you pick will load.
          </>
        }
      >
        <div className="mt-4">
          <GpuList hardware={hardware} />
        </div>
      </Panel>

      <InstalledModels llm={llm} />
    </div>
  );
}
