import { useMemo, useState, type MouseEvent as ReactMouseEvent } from 'react';
import { X } from 'lucide-react';
import { Button, cn } from '@/components/ui/core';
import { AGENT_CONFIGS, DEPENDENCY_CHECKS } from './AgentConfigs';
import type { AgentType, OnboardingPhase, Platform } from './types';

interface OnboardingOverlayProps {
  baseUrl: string;
  backendHint: string | null;
  onComplete: (agent: AgentType) => void;
  onInsertCommand: (command: string) => void;
  onDismiss: () => void;
  onNeverShowAgainChange: (neverShowAgain: boolean) => void;
}

type DependencyStatus = 'idle' | 'checking' | 'passed' | 'install';

const STEPS: { key: OnboardingPhase; label: string }[] = [
  { key: 'os-selection', label: 'Start' },
  { key: 'agent-selection', label: 'Agent' },
  { key: 'dependency-check', label: 'Checks' },
  { key: 'install-agent', label: 'Install' },
  { key: 'launch-agent', label: 'Launch' },
];

const PLATFORM_LABELS: Record<Platform, string> = {
  windows: 'Windows',
  macos: 'macOS',
  linux: 'Linux',
};

const FIRST_PROMPT = [
  "You are running inside MARM Console's embedded terminal.",
  'MARM is a local-first AI memory and code-graph MCP server: persistent session memory, semantic recall, a concept graph, and an indexed code graph for connected repositories.',
  'If this agent is configured with the MARM MCP server, its marm_* tools are already available in this session.',
  'Start by confirming what MARM tools you can see, then briefly summarize what you can help with here.',
].join(' ');

export function OnboardingOverlay({ baseUrl, backendHint, onComplete, onInsertCommand, onDismiss, onNeverShowAgainChange }: OnboardingOverlayProps) {
  const [phase, setPhase] = useState<OnboardingPhase>('os-selection');
  const [neverShowAgain, setNeverShowAgain] = useState(false);
  const [platform, setPlatform] = useState<Platform | null>(backendHint === 'conpty' ? 'windows' : null);
  const [selectedAgent, setSelectedAgent] = useState<AgentType | null>(null);
  const [dragOffset, setDragOffset] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const [dependencyStatus, setDependencyStatus] = useState<Record<string, DependencyStatus>>({});
  const [dependencyOutput, setDependencyOutput] = useState<Record<string, string>>({});
  const [lastInsertedStep, setLastInsertedStep] = useState<'install' | 'verify' | 'launch' | null>(null);

  const agentConfig = selectedAgent ? AGENT_CONFIGS.find((agent) => agent.id === selectedAgent) : null;
  const agentCommands = agentConfig && platform ? agentConfig.commands[platform] : null;
  const phaseIndex = STEPS.findIndex((step) => step.key === phase);
  const allDependenciesPassed = DEPENDENCY_CHECKS.every((dep) => dependencyStatus[dep.name] === 'passed');

  const summarizeOutput = (output: string, success: boolean) => {
    const lines = output
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter((line) => line.length > 0 && !/^npm warn\b/i.test(line) && !/^warning[:\s]/i.test(line));
    if (lines.length === 0) return success ? 'Installed' : 'No version output returned';
    return lines.slice(0, 2).join(' ');
  };

  const runDependencyCheck = async (name: string, command: string) => {
    setDependencyStatus((current) => ({ ...current, [name]: 'checking' }));
    try {
      const response = await fetch(`${baseUrl}/api/terminal/check`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command }),
      });
      const result = (await response.json()) as { success: boolean; output: string };
      setDependencyStatus((current) => ({ ...current, [name]: result.success ? 'passed' : 'install' }));
      setDependencyOutput((current) => ({ ...current, [name]: summarizeOutput(result.output ?? '', result.success) }));
    } catch {
      setDependencyStatus((current) => ({ ...current, [name]: 'install' }));
      setDependencyOutput((current) => ({ ...current, [name]: 'Check failed. Install it yourself and re-run Check.' }));
    }
  };

  const handleDependencyAction = (name: string, command: string, installCommand: string) => {
    const status = dependencyStatus[name] ?? 'idle';
    if (status === 'install') {
      if (platform === 'windows') {
        onInsertCommand(installCommand + '\r');
        setDependencyOutput((current) => ({ ...current, [name]: `Inserted install command: ${installCommand}` }));
      }
      return;
    }
    if (status === 'passed' || status === 'checking') return;
    void runDependencyCheck(name, command);
  };

  const handleInsertCommand = (command: string, step: 'install' | 'verify' | 'launch') => {
    onInsertCommand(command + '\r');
    setLastInsertedStep(step);
  };

  const handleCardMouseDown = (event: ReactMouseEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest('button, input, select, textarea, a, code, [role="button"]')) return;

    event.preventDefault();
    const startX = event.clientX;
    const startY = event.clientY;
    const initialOffset = { ...dragOffset };

    const onMove = (moveEvent: globalThis.MouseEvent) => {
      setIsDragging(true);
      setDragOffset({ x: initialOffset.x + (moveEvent.clientX - startX), y: initialOffset.y + (moveEvent.clientY - startY) });
    };
    const onUp = () => {
      setIsDragging(false);
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  const cardStyle = useMemo(() => ({ transform: `translate(${dragOffset.x}px, ${dragOffset.y}px)` }), [dragOffset]);

  const StepRail = () => (
    <div className="flex items-center gap-2" aria-hidden="true">
      {STEPS.map((step, index) => (
        <div key={step.key} className="flex items-center gap-1.5">
          <span className={cn('h-1.5 w-1.5 rounded-full', index === phaseIndex ? 'bg-primary' : index < phaseIndex ? 'bg-primary/50' : 'bg-muted-foreground/30')} />
          <span className={cn('text-[10px] uppercase tracking-wide', index === phaseIndex ? 'text-primary' : 'text-muted-foreground')}>{step.label}</span>
        </div>
      ))}
    </div>
  );

  const CardShell = ({ title, subtitle, wide, children }: { title: string; subtitle: string; wide?: boolean; children: React.ReactNode }) => (
    <div className="absolute inset-0 z-30 flex items-start justify-center overflow-y-auto bg-black/40 p-6">
      <div
        style={cardStyle}
        className={cn('mt-4 w-full space-y-4 rounded-xl border border-border/80 bg-card/95 p-5 shadow-[0_18px_44px_rgba(0,0,0,0.4)] backdrop-blur-xl', wide ? 'max-w-2xl' : 'max-w-md')}
      >
        <div className={cn('cursor-move select-none space-y-3', isDragging && 'opacity-90')} onMouseDown={handleCardMouseDown}>
          <StepRail />
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold">{title}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
            </div>
            <button type="button" aria-label="Close guide" onClick={onDismiss} className="shrink-0 text-muted-foreground hover:text-foreground">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        {children}
      </div>
    </div>
  );

  if (phase === 'os-selection') {
    return (
      <CardShell title="Welcome to the terminal" subtitle="This is a real shell running on the machine hosting MARM Console, wired straight into your browser. Pick your operating system so the next steps show the right commands.">
        <div className="grid grid-cols-3 gap-2">
          {(['windows', 'macos', 'linux'] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setPlatform(option)}
              className={cn(
                'rounded-lg border p-3 text-center text-sm font-medium transition-colors',
                platform === option ? 'border-primary/55 bg-primary/15 text-primary' : 'border-border/70 bg-background/40 text-muted-foreground hover:border-primary/40 hover:text-foreground'
              )}
            >
              {PLATFORM_LABELS[option]}
            </button>
          ))}
        </div>
        <div className="flex items-center justify-between gap-2">
          <label className="flex items-center gap-2 text-xs text-muted-foreground">
            <input
              type="checkbox"
              checked={neverShowAgain}
              onChange={(event) => {
                setNeverShowAgain(event.target.checked);
                onNeverShowAgainChange(event.target.checked);
              }}
            />
            Don't launch on startup
          </label>
          <Button disabled={!platform} onClick={() => setPhase('agent-selection')}>Continue</Button>
        </div>
      </CardShell>
    );
  }

  if (phase === 'agent-selection') {
    return (
      <CardShell title="Choose Your AI Assistant" subtitle="Pick the CLI you want to use in this terminal.">
        <div className="grid gap-2 sm:grid-cols-3">
          {AGENT_CONFIGS.map((agent) => (
            <button
              key={agent.id}
              type="button"
              onClick={() => {
                setSelectedAgent(agent.id);
                setLastInsertedStep(null);
                setPhase('dependency-check');
              }}
              className="rounded-lg border border-border/70 bg-background/40 p-3 text-left transition-colors hover:border-primary/55 hover:bg-primary/10"
            >
              <div className="text-sm font-semibold">{agent.name}</div>
              <div className="mt-1 text-xs text-muted-foreground">{agent.description}</div>
            </button>
          ))}
        </div>
        <div className="flex justify-start">
          <Button variant="outline" onClick={() => setPhase('os-selection')}>Back</Button>
        </div>
      </CardShell>
    );
  }

  if (phase === 'dependency-check') {
    return (
      <CardShell title="Check Terminal Dependencies" subtitle="Run these checks first. If a tool is missing, install it and re-run Check.">
        <div className="space-y-2">
          {DEPENDENCY_CHECKS.map((dep) => {
            const status = dependencyStatus[dep.name] ?? 'idle';
            return (
              <div key={dep.name} className="flex items-center justify-between gap-3 rounded-lg border border-border/70 bg-background/40 p-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium">{dep.name}</div>
                  <div className="mt-0.5 truncate text-xs text-muted-foreground">
                    {dependencyOutput[dep.name] || (status === 'install' && platform !== 'windows' ? "Install it via your platform's package manager, then re-run Check." : 'Run Check to confirm the installed version.')}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className={cn('rounded px-2 py-0.5 text-[10px] font-semibold uppercase', status === 'passed' ? 'bg-emerald-500/15 text-emerald-400' : status === 'install' ? 'bg-amber-500/15 text-amber-400' : 'bg-muted/40 text-muted-foreground')}>
                    {status === 'checking' ? 'Checking' : status === 'passed' ? 'Ready' : status === 'install' ? 'Missing' : 'Unchecked'}
                  </span>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={status === 'checking' || status === 'passed' || (status === 'install' && platform !== 'windows')}
                    onClick={() => handleDependencyAction(dep.name, dep.command, dep.installCommand)}
                  >
                    {status === 'checking' ? 'Checking...' : status === 'passed' ? 'Passed' : status === 'install' ? (platform === 'windows' ? 'Install' : 'Missing') : 'Check'}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
        <p className="text-xs text-muted-foreground">
          {allDependenciesPassed ? 'All checks passed.' : 'Version output means the tool is installed. If a check fails, install it, then re-run Check.'}
        </p>
        <div className="flex justify-between gap-2">
          <Button variant="outline" onClick={() => setPhase('agent-selection')}>Back</Button>
          {allDependenciesPassed && <Button onClick={() => setPhase('install-agent')}>Continue</Button>}
        </div>
      </CardShell>
    );
  }

  if (phase === 'install-agent' && agentConfig && agentCommands) {
    return (
      <CardShell title={`Install ${agentConfig.name}`} subtitle="Send one command at a time and watch the terminal output before continuing.">
        <div className="space-y-3">
          <CommandRow title="1. Install the CLI" description="Run this first and wait for it to finish before verifying." command={agentCommands.install} sent={lastInsertedStep === 'install'} onSend={() => handleInsertCommand(agentCommands.install, 'install')} />
          <CommandRow title="2. Verify the install" description="Run this once the install step succeeds." command={agentCommands.verify} sent={lastInsertedStep === 'verify'} onSend={() => handleInsertCommand(agentCommands.verify, 'verify')} />
        </div>
        <div className="flex justify-between gap-2">
          <Button variant="outline" onClick={() => setPhase('dependency-check')}>Back</Button>
          <Button onClick={() => setPhase('launch-agent')}>Continue</Button>
        </div>
      </CardShell>
    );
  }

  if (phase === 'launch-agent' && agentConfig && agentCommands) {
    return (
      <CardShell title={`${agentConfig.name} is ready to launch`} subtitle="Launch the CLI, then send the first prompt to give it MARM context." wide>
        <div className="space-y-3">
          <CommandRow title={`1. Launch ${agentConfig.name}`} description="Send into the active terminal session." command={agentCommands.launch} sent={lastInsertedStep === 'launch'} onSend={() => handleInsertCommand(agentCommands.launch, 'launch')} />
          <div className="space-y-1.5">
            <div className="text-sm font-medium">2. First prompt (double-click to send)</div>
            <div
              onDoubleClick={() => onInsertCommand(FIRST_PROMPT + '\r')}
              title="Double-click to insert into the terminal"
              className="cursor-pointer rounded-lg border border-dashed border-border/70 bg-background/40 p-3 font-mono text-xs text-muted-foreground hover:border-primary/55"
            >
              {FIRST_PROMPT}
            </div>
          </div>
        </div>
        <div className="flex justify-between gap-2">
          <Button variant="outline" onClick={() => setPhase('install-agent')}>Back</Button>
          <Button onClick={() => onComplete(agentConfig.id)}>Done</Button>
        </div>
      </CardShell>
    );
  }

  return null;
}

function CommandRow({ title, description, command, sent, onSend }: { title: string; description: string; command: string; sent: boolean; onSend: () => void }) {
  return (
    <div className="space-y-1.5">
      <div className="text-sm font-medium">{title}</div>
      <div className="text-xs text-muted-foreground">{description}</div>
      <div className="flex items-center justify-between gap-3 rounded-lg border border-border/70 bg-background/40 p-2.5">
        <code className="truncate font-mono text-xs">{command}</code>
        <Button size="sm" variant="outline" onClick={onSend} className="shrink-0">{sent ? 'Sent' : 'Send'}</Button>
      </div>
    </div>
  );
}
