import { useMemo, useState } from 'react';
import { TriangleAlert } from 'lucide-react';
import { useConnectionsOverview, useManualCli } from '@/hooks/use-marm-queries';
import { Button, Input } from '@/components/ui/core';
import { CopyButton } from '@/components/code-context/shared';
import type { ManualCliArg, ManualCliCommand } from '@/lib/marm-types';
import { ErrorState, NativeSelect, Toggle, mutationMessage } from './controls';
import { CodeBlock, Field, SendToTerminal } from './manualShared';

const CLI_NAME = 'marm-memory';

type ArgValue = boolean | string | string[];
type Values = Record<string, ArgValue>;

export type QuoteShell = 'posix' | 'powershell';

export function quoteArg(value: string, shell: QuoteShell = 'posix') {
  if (/^[\w@%+=:,./\\-]+$/.test(value)) return value;
  if (shell === 'powershell') return `'${value.replace(/'/g, "''")}'`;
  if (/[$`]/.test(value) && !value.includes("'")) return `'${value}'`;
  const escaped = value.replace(/\\/g, '\\\\').replace(/["$`]/g, '\\$&');
  return `"${escaped}"`;
}

function valuesOf(arg: ManualCliArg, values: Values): string[] {
  const raw = values[arg.name];
  const list = Array.isArray(raw) ? raw : typeof raw === 'string' ? [raw] : [];
  return list.map((item) => item.trim()).filter(Boolean);
}

export function buildCommandLine(command: ManualCliCommand, values: Values, shell: QuoteShell = 'posix') {
  const parts = [CLI_NAME, command.command];
  const positionals = command.args.filter((arg) => arg.kind === 'positional');
  const others = command.args.filter((arg) => arg.kind !== 'positional');
  for (const arg of positionals) parts.push(...valuesOf(arg, values).map((value) => quoteArg(value, shell)));
  for (const arg of others) {
    const flag = arg.flag ?? `--${arg.name}`;
    if (arg.kind === 'flag') {
      if (values[arg.name] === true) parts.push(flag);
    } else {
      for (const value of valuesOf(arg, values)) parts.push(flag, quoteArg(value, shell));
    }
  }
  return parts.join(' ');
}

function groupOf(command: ManualCliCommand) {
  return command.command.split(' ')[0];
}

export function CliSection() {
  const cli = useManualCli();
  const overview = useConnectionsOverview();
  const shell: QuoteShell = /^windows/i.test(overview.data?.os ?? '') ? 'powershell' : 'posix';
  const commands = useMemo(() => cli.data?.commands ?? [], [cli.data]);
  const buildable = commands.filter((command) => !command.cli_only);
  const cliOnly = commands.filter((command) => command.cli_only);
  const [selected, setSelected] = useState('');
  const [values, setValues] = useState<Values>({});

  const command = buildable.find((item) => item.command === selected) ?? buildable[0];
  const groups = useMemo(() => {
    const grouped = new Map<string, ManualCliCommand[]>();
    for (const item of buildable) grouped.set(groupOf(item), [...(grouped.get(groupOf(item)) ?? []), item]);
    return [...grouped.entries()];
  }, [buildable]);

  if (cli.isLoading) return <p className="text-sm text-muted-foreground">Loading commands...</p>;
  if (cli.isError) return <ErrorState message={mutationMessage(cli.error)} />;

  const line = command ? buildCommandLine(command, values, shell) : '';
  const setValue = (name: string, value: ArgValue) => setValues((current) => ({ ...current, [name]: value }));
  const ordered = command ? [...command.args.filter((arg) => arg.kind === 'positional'), ...command.args.filter((arg) => arg.kind !== 'positional')] : [];

  return (
    <div className="space-y-4">
      <Field label="Command" className="max-w-md">
        <NativeSelect
          value={command?.command ?? ''}
          onChange={(event) => {
            setSelected(event.target.value);
            setValues({});
          }}
        >
          {groups.map(([group, items]) => (
            <optgroup key={group} label={group}>
              {items.map((item) => <option key={item.command} value={item.command}>{item.command}</option>)}
            </optgroup>
          ))}
        </NativeSelect>
      </Field>
      {command && <p className="text-xs text-muted-foreground">{command.help}</p>}

      {ordered.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          {ordered.map((arg) => <ArgControl key={`${command?.command}:${arg.name}`} arg={arg} value={values[arg.name]} onChange={(next) => setValue(arg.name, next)} />)}
        </div>
      )}

      <CodeBlock text={line} label="command" />
      <div className="flex flex-wrap items-center gap-3">
        <SendToTerminal command={line} />
        <span className="text-xs text-muted-foreground">Sending only types the command. You press Enter to run it.</span>
      </div>

      {cliOnly.length > 0 && (
        <div className="rounded-lg border border-amber-400/25 bg-amber-400/[0.06] p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-amber-300"><TriangleAlert className="h-4 w-4" />Run these yourself</div>
          <p className="mb-3 text-xs text-muted-foreground">These stay in your own terminal, so they are not sent from here.</p>
          <ul className="space-y-2">
            {cliOnly.map((item) => (
              <li key={item.command} className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <code className="font-mono text-xs">{`${CLI_NAME} ${item.command}`}</code>
                  {item.cli_only_reason && <p className="text-xs text-muted-foreground">{item.cli_only_reason}</p>}
                </div>
                <CopyButton value={`${CLI_NAME} ${item.command}`} label={`Copy ${item.command}`} className="h-7 w-7 shrink-0" />
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ArgControl({ arg, value, onChange }: { arg: ManualCliArg; value: ArgValue | undefined; onChange: (next: ArgValue) => void }) {
  const title = arg.kind === 'positional' ? arg.name : (arg.flag ?? arg.name);
  const hint = arg.default !== null && arg.default !== undefined && arg.default !== false ? `default ${String(arg.default)}` : arg.help;

  if (arg.kind === 'flag') {
    return (
      <div className="flex items-center justify-between gap-3 rounded-lg border border-border/60 px-3 py-2">
        <div className="min-w-0">
          <div className="font-mono text-xs">{title}</div>
          <div className="text-[11px] text-muted-foreground">{arg.help}</div>
          {arg.cli_only && <div className="text-[11px] text-amber-300">{arg.cli_only_reason ?? 'Run this in a terminal.'}</div>}
        </div>
        <Toggle checked={value === true} onChange={onChange} label={title} />
      </div>
    );
  }

  if (arg.repeatable) {
    const list = Array.isArray(value) ? value : [];
    return (
      <div className="space-y-1.5 rounded-lg border border-border/60 p-3">
        <div className="font-mono text-xs">{title}</div>
        {list.map((item, index) => (
          <div key={index} className="flex gap-2">
            <Input aria-label={`${title} ${index + 1}`} value={item} onChange={(event) => onChange(list.map((entry, at) => (at === index ? event.target.value : entry)))} />
            <Button type="button" variant="ghost" size="sm" aria-label={`Remove ${title} ${index + 1}`} onClick={() => onChange(list.filter((_, at) => at !== index))}>Remove</Button>
          </div>
        ))}
        <Button type="button" variant="outline" size="sm" aria-label={`Add ${title}`} onClick={() => onChange([...list, ''])}>Add</Button>
        {arg.help && <div className="text-[11px] text-muted-foreground">{arg.help}</div>}
      </div>
    );
  }

  const text = typeof value === 'string' ? value : '';
  return (
    <Field label={title}>
      {arg.choices && arg.choices.length > 0 ? (
        <NativeSelect aria-label={title} value={text} onChange={(event) => onChange(event.target.value)}>
          <option value="">{arg.default !== null && arg.default !== undefined ? `Default (${String(arg.default)})` : 'Not set'}</option>
          {arg.choices.map((choice) => <option key={choice} value={choice}>{choice}</option>)}
        </NativeSelect>
      ) : (
        <Input aria-label={title} type={arg.type === 'int' ? 'number' : 'text'} placeholder={hint} value={text} onChange={(event) => onChange(event.target.value)} />
      )}
      {arg.help && <span className="text-[11px] font-normal">{arg.help}</span>}
    </Field>
  );
}
