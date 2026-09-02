import { useEffect, useRef, useState } from 'react';
import { CircleAlert, Eraser, Keyboard, Minus, Plus, Settings2, Sparkles, Square, X } from 'lucide-react';
import { cn } from '@/components/ui/core';
import { useMarmConfig } from '@/hooks/use-marm-queries';
import { KeyboardShortcutsDialog } from './KeyboardShortcutsDialog';
import { OnboardingOverlay } from './OnboardingOverlay';
import { TerminalSessionView, type ConnectionState, type TerminalSessionHandle } from './TerminalSessionView';
import { TerminalSettingsDialog } from './TerminalSettingsDialog';
import { DEFAULT_TERMINAL_SETTINGS, type AgentType, type TerminalSettings } from './types';

type TerminalStatus = {
  available: boolean;
  reason: string;
  backend: string;
  shell: string | null;
};

interface TerminalSessionState {
  id: string;
  label: string;
  connectionState: ConnectionState;
  serverSessionId?: string;
}

const MIN_HEIGHT = 200;
const MAX_SESSIONS = 10;
const DEFAULT_HEIGHT = 340;
const MAX_HEIGHT_RATIO = 0.7;
const SETTINGS_STORAGE_KEY = 'marm-console:terminal-settings';
const GUIDE_DISMISSED_STORAGE_KEY = 'marm-console:terminal-guide-dismissed:v2';
// sessionStorage, not localStorage: this only needs to survive a page
// refresh, not a fully closed tab -- reopening the tab later starting fresh
// is the right default, and it keeps a stale entry from outliving the PTY
// sessions it describes by more than one browser session.
const DOCK_STATE_STORAGE_KEY = 'marm-console:terminal-dock-state';

interface PersistedDockState {
  open: boolean;
  minimized: boolean;
  sessions: { id: string; label: string; serverSessionId?: string }[];
  activeSessionId: string | null;
}

function loadPersistedDockState(): PersistedDockState | null {
  try {
    const raw = window.sessionStorage.getItem(DOCK_STATE_STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as PersistedDockState;
  } catch {
    return null;
  }
}

export function readPersistedDockOpen(): boolean {
  return loadPersistedDockState()?.open ?? false;
}

function loadStoredSettings(): TerminalSettings {
  try {
    const raw = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
    if (!raw) return DEFAULT_TERMINAL_SETTINGS;
    const stored = JSON.parse(raw) as Partial<TerminalSettings>;
    return {
      profile: { ...DEFAULT_TERMINAL_SETTINGS.profile, ...stored.profile },
      appearance: { ...DEFAULT_TERMINAL_SETTINGS.appearance, ...stored.appearance },
      clipboard: { ...DEFAULT_TERMINAL_SETTINGS.clipboard, ...stored.clipboard },
      scrollback: { ...DEFAULT_TERMINAL_SETTINGS.scrollback, ...stored.scrollback },
      notifications: { ...DEFAULT_TERMINAL_SETTINGS.notifications, ...stored.notifications },
    };
  } catch {
    return DEFAULT_TERMINAL_SETTINGS;
  }
}

function nextSessionLabel(format: string, sessionNumber: number) {
  return format.replace('{n}', String(sessionNumber));
}

interface TerminalDockProps {
  open: boolean;
  onClose: () => void;
}

export function TerminalDock({ open, onClose }: TerminalDockProps) {
  const { baseUrl } = useMarmConfig();
  const [status, setStatus] = useState<TerminalStatus | null>(null);
  const [statusError, setStatusError] = useState('');
  const [minimized, setMinimized] = useState(() => loadPersistedDockState()?.minimized ?? false);
  const [sessions, setSessions] = useState<TerminalSessionState[]>(() =>
    (loadPersistedDockState()?.sessions ?? []).map((session) => ({ ...session, connectionState: 'idle' as ConnectionState }))
  );
  const [activeSessionId, setActiveSessionId] = useState<string | null>(() => loadPersistedDockState()?.activeSessionId ?? null);
  const [settings, setSettings] = useState<TerminalSettings>(loadStoredSettings);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const [shellVersion, setShellVersion] = useState<string | null>(null);
  const dockRef = useRef<HTMLDivElement>(null);
  const sessionRefs = useRef<Record<string, TerminalSessionHandle | null>>({});

  useEffect(() => {
    if (!open || status) return;
    let cancelled = false;
    fetch(`${baseUrl}/api/terminal/status`, { credentials: 'same-origin' })
      .then((res) => {
        if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
        return res.json();
      })
      .then((data: TerminalStatus) => {
        if (!cancelled) {
          setStatusError('');
          setStatus(data);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) setStatusError(error instanceof Error ? error.message : 'Could not reach the terminal status endpoint.');
      });
    return () => {
      cancelled = true;
    };
  }, [open, status, baseUrl]);

  useEffect(() => {
    if (!status?.shell || shellVersion) return;
    const shellName = status.shell.split(/[\\/]/).pop()?.toLowerCase() ?? '';
    const versionCheck = shellName.startsWith('pwsh') || shellName.startsWith('powershell')
      ? { label: 'PowerShell', command: '$PSVersionTable.PSVersion.ToString()' }
      : shellName.startsWith('bash')
        ? { label: 'Bash', command: 'bash --version' }
        : shellName.startsWith('zsh')
          ? { label: 'Zsh', command: 'zsh --version' }
          : shellName.startsWith('cmd')
            ? { label: 'CMD', command: 'ver' }
            : null;
    if (!versionCheck) return;

    let cancelled = false;
    fetch(`${baseUrl}/api/terminal/check`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: versionCheck.command }),
    })
      .then((res) => res.json())
      .then((result: { success: boolean; output: string }) => {
        if (cancelled || !result.success) return;
        const version = result.output.match(/\d+\.\d+(\.\d+)?/)?.[0];
        if (version) setShellVersion(`${versionCheck.label} ${version}`);
      })
      .catch(() => {
        // Non-fatal; the header just omits the version badge.
      });
    return () => {
      cancelled = true;
    };
  }, [status?.shell, shellVersion, baseUrl]);

  useEffect(() => {
    if (open && status?.available && sessions.length === 0) {
      const id = crypto.randomUUID();
      setSessions([{ id, label: nextSessionLabel(settings.scrollback.customTitleFormat, 1), connectionState: 'idle' }]);
      setActiveSessionId(id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, status?.available]);

  useEffect(() => {
    try {
      const payload: PersistedDockState = {
        open,
        minimized,
        sessions: sessions.map(({ id, label, serverSessionId }) => ({ id, label, serverSessionId })),
        activeSessionId,
      };
      window.sessionStorage.setItem(DOCK_STATE_STORAGE_KEY, JSON.stringify(payload));
    } catch {
      // Non-fatal; the dock just won't survive a refresh if storage is blocked.
    }
  }, [open, minimized, sessions, activeSessionId]);

  useEffect(() => {
    try {
      window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(settings));
    } catch {
      // Settings still apply for the current session even if storage is blocked.
    }
  }, [settings]);

  useEffect(() => {
    if (!open) return;
    try {
      if (window.localStorage.getItem(GUIDE_DISMISSED_STORAGE_KEY) !== '1') setGuideOpen(true);
    } catch {
      // If storage is blocked, just skip auto-opening the guide.
    }
  }, [open]);

  const addSession = () => {
    if (sessions.length >= MAX_SESSIONS) return;
    const id = crypto.randomUUID();
    setSessions((current) => [...current, { id, label: nextSessionLabel(settings.scrollback.customTitleFormat, current.length + 1), connectionState: 'idle' }]);
    setActiveSessionId(id);
  };

  const closeSession = (id: string) => {
    sessionRefs.current[id]?.sendKill();
    delete sessionRefs.current[id];
    setSessions((current) => {
      const remaining = current.filter((session) => session.id !== id);
      setActiveSessionId((activeId) => {
        if (activeId !== id) return activeId;
        return remaining.length > 0 ? remaining[remaining.length - 1].id : null;
      });
      return remaining;
    });
  };

  const updateConnectionState = (id: string, state: ConnectionState) => {
    setSessions((current) => current.map((session) => (session.id === id ? { ...session, connectionState: state } : session)));
  };

  const updateServerSessionId = (id: string, serverSessionId: string) => {
    setSessions((current) => current.map((session) => (session.id === id ? { ...session, serverSessionId } : session)));
  };

  const startResize = (event: React.MouseEvent) => {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = dockRef.current?.clientHeight ?? DEFAULT_HEIGHT;

    const handleMouseMove = (moveEvent: MouseEvent) => {
      const delta = startY - moveEvent.clientY;
      const maxHeight = window.innerHeight * MAX_HEIGHT_RATIO;
      const nextHeight = Math.max(MIN_HEIGHT, Math.min(maxHeight, startHeight + delta));
      if (dockRef.current) dockRef.current.style.height = `${nextHeight}px`;
    };
    const handleMouseUp = () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  };

  const handleClose = () => {
    setMinimized(false);
    onClose();
  };

  const closeGuide = () => setGuideOpen(false);

  const setGuideDismissedForever = (neverShowAgain: boolean) => {
    try {
      if (neverShowAgain) window.localStorage.setItem(GUIDE_DISMISSED_STORAGE_KEY, '1');
      else window.localStorage.removeItem(GUIDE_DISMISSED_STORAGE_KEY);
    } catch {
      // Non-fatal; the guide will just keep its default auto-open behavior.
    }
  };

  const insertCommand = (command: string) => {
    if (activeSessionId) sessionRefs.current[activeSessionId]?.sendInput(command);
  };

  const showNotice = statusError || !status || !status.available;
  const activeConnectionState = sessions.find((session) => session.id === activeSessionId)?.connectionState ?? 'idle';
  const dockHidden = !open || minimized;

  return (
    <>
      <button
        type="button"
        onClick={() => setMinimized(false)}
        style={open && minimized ? undefined : { display: 'none' }}
        className="fixed bottom-0 left-0 right-0 z-40 flex h-9 items-center justify-between border-t border-border/70 bg-sidebar/95 px-4 text-xs text-muted-foreground backdrop-blur-xl transition-colors hover:text-foreground"
      >
        <span>Terminal · click to expand</span>
        <span className="uppercase tracking-wide">{activeConnectionState}</span>
      </button>
      <div
        ref={dockRef}
        style={dockHidden ? { display: 'none' } : { height: DEFAULT_HEIGHT }}
        className="fixed bottom-0 left-0 right-0 z-40 flex flex-col overflow-hidden border-t border-border/80 bg-[#0b0f14] shadow-[0_-18px_44px_rgba(0,0,0,0.35)]"
      >
        <div onMouseDown={startResize} className="h-1.5 w-full shrink-0 cursor-row-resize bg-transparent transition-colors hover:bg-primary/40" />

        <div className="relative flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-border/60 px-3 py-2">
          {shellVersion && (
            <div className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-1 font-mono text-xs font-semibold text-primary">
              {shellVersion}
            </div>
          )}
          <div className="flex min-w-0 flex-wrap items-center gap-1.5">
            {sessions.map((session) => (
              <button
                key={session.id}
                type="button"
                onClick={() => setActiveSessionId(session.id)}
                className={cn(
                  'group flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors',
                  session.id === activeSessionId ? 'border-primary/45 bg-primary/15 text-primary' : 'border-border/70 bg-background/40 text-muted-foreground hover:text-foreground'
                )}
              >
                <span>{session.label}</span>
                <span
                  role="button"
                  aria-label={`Close ${session.label}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    closeSession(session.id);
                  }}
                  className="opacity-0 transition-opacity group-hover:opacity-100"
                >
                  ×
                </span>
              </button>
            ))}
            {sessions.length < MAX_SESSIONS && (
              <button type="button" aria-label="New terminal" onClick={addSession} className="flex h-6 w-6 items-center justify-center rounded-full border border-border/70 bg-background/40 text-muted-foreground hover:border-primary/45 hover:text-primary">
                <Plus className="h-3 w-3" />
              </button>
            )}
          </div>
          <div className="flex items-center gap-1">
            <HeaderIconButton label="Clear terminal" onClick={() => activeSessionId && sessionRefs.current[activeSessionId]?.sendClear()}><Eraser className="h-3.5 w-3.5" /></HeaderIconButton>
            <HeaderIconButton label="Terminal guide" onClick={() => setGuideOpen(true)}><Sparkles className="h-3.5 w-3.5" /></HeaderIconButton>
            <HeaderIconButton label="Keyboard shortcuts" onClick={() => setShortcutsOpen(true)}><Keyboard className="h-3.5 w-3.5" /></HeaderIconButton>
            <HeaderIconButton label="Terminal settings" onClick={() => setSettingsOpen(true)}><Settings2 className="h-3.5 w-3.5" /></HeaderIconButton>
            <HeaderIconButton label="Minimize terminal" onClick={() => setMinimized(true)}><Minus className="h-3.5 w-3.5" /></HeaderIconButton>
            <HeaderIconButton label="Close terminal" onClick={handleClose}><X className="h-3.5 w-3.5" /></HeaderIconButton>
          </div>
        </div>

        <div className="relative min-h-0 flex-1">
          {showNotice ? (
            statusError ? (
              <DockNotice icon={<CircleAlert className="h-4 w-4" />} title="Status check failed" detail={statusError} />
            ) : !status ? (
              <DockNotice icon={<Square className="h-4 w-4" />} title="Checking availability..." detail="Contacting /api/terminal/status." />
            ) : (
              <DockNotice icon={<CircleAlert className="h-4 w-4" />} title="Terminal unavailable" detail={status.reason} />
            )
          ) : (
            sessions.map((session) => (
              <TerminalSessionView
                key={session.id}
                ref={(handle) => {
                  sessionRefs.current[session.id] = handle;
                }}
                active={session.id === activeSessionId}
                baseUrl={baseUrl}
                cwd={settings.profile.customPath || undefined}
                shellHint={status?.shell ?? null}
                settings={settings}
                resumeSessionId={session.serverSessionId}
                onConnectionStateChange={(state) => updateConnectionState(session.id, state)}
                onSessionIdChange={(serverSessionId) => updateServerSessionId(session.id, serverSessionId)}
              />
            ))
          )}
          {guideOpen && (
            <OnboardingOverlay
              baseUrl={baseUrl}
              backendHint={status?.backend ?? null}
              onDismiss={closeGuide}
              onNeverShowAgainChange={setGuideDismissedForever}
              onInsertCommand={insertCommand}
              onComplete={(agent: AgentType) => {
                void agent;
                closeGuide();
              }}
            />
          )}
        </div>
      </div>

      <TerminalSettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} settings={settings} onSave={setSettings} />
      <KeyboardShortcutsDialog open={shortcutsOpen} onOpenChange={setShortcutsOpen} />
    </>
  );
}

function HeaderIconButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} className="flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent/60 hover:text-foreground">
      {children}
    </button>
  );
}

function DockNotice({ icon, title, detail }: { icon: React.ReactNode; title: string; detail: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
      <div className="flex items-center gap-2 text-sm font-semibold text-foreground">{icon} {title}</div>
      <p className="max-w-md text-xs text-muted-foreground">{detail}</p>
    </div>
  );
}
