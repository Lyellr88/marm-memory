import { useEffect, useRef, useState } from 'react';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { Link, useLocation } from 'wouter';
import { useOverview, isAuthError } from '@/hooks/use-marm-queries';
import { SettingsDialog } from './SettingsDialog';
import { TerminalDock, readPersistedDockOpen } from '@/components/terminal/TerminalDock';
import { Settings, Database, Activity, Compass, Network, FolderCode, ServerCog, AppWindowMac, ChevronRight } from 'lucide-react';
import { cn } from '@/components/ui/core';

const THEME_STORAGE_KEY = 'marm-console-accent';
const ACCENT_THEMES = [
  { id: 'cyan', label: 'Cyan', color: '#20b8f4' },
  { id: 'emerald', label: 'Emerald', color: '#10b981' },
  { id: 'violet', label: 'Violet', color: '#a855f7' },
  { id: 'orange', label: 'Orange', color: '#f97316' },
  { id: 'blue', label: 'Blue', color: '#3b82f6' },
  { id: 'slate', label: 'Slate', color: '#94a3b8' },
] as const;

type AccentTheme = (typeof ACCENT_THEMES)[number]['id'];

function getInitialTheme(): AccentTheme {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (ACCENT_THEMES.some((theme) => theme.id === stored)) return stored as AccentTheme;
  } catch {
    // The default remains available when browser storage is blocked.
  }
  return 'cyan';
}

export function Shell({ children }: { children: React.ReactNode }) {
  const [location] = useLocation();
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [terminalOpen, setTerminalOpen] = useState(readPersistedDockOpen);
  const [accentTheme, setAccentTheme] = useState<AccentTheme>(getInitialTheme);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const { data, error, isFetching } = useOverview();

  useEffect(() => {
    document.documentElement.dataset.marmTheme = accentTheme;
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, accentTheme);
    } catch {
      // Theme selection still applies for the current session.
    }
  }, [accentTheme]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.key === '`') {
        event.preventDefault();
        setTerminalOpen((current) => !current);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  let statusColor = 'bg-gray-500';
  let statusText = 'Disconnected';
  let statusPulse = false;

  if (isFetching && !data && !error) {
    statusColor = 'bg-blue-500';
    statusText = 'Connecting...';
    statusPulse = true;
  } else if (error) {
    if (isAuthError(error)) {
      statusColor = 'bg-amber-500';
      statusText = 'Needs Key';
      statusPulse = true;
    } else {
      statusColor = 'bg-destructive';
      statusText = 'Unreachable';
    }
  } else if (data) {
    statusColor = 'bg-emerald-400';
    statusText = 'Connected';
    statusPulse = true;
  }

  const navItems = [
    { name: 'Overview', href: '/', icon: Activity },
    { name: 'Memories', href: '/memory', icon: Database },
    { name: 'Knowledge Graph', href: '/knowledge', icon: Network },
    { name: 'Indexed Projects', href: '/projects', icon: FolderCode },
    { name: 'Project Explorer', href: '/explorer', icon: Compass },
    { name: 'System', href: '/system', icon: ServerCog },
  ];

  return (
    <DialogPrimitive.Root open={navigationOpen} onOpenChange={setNavigationOpen}>
      <div className="flex h-screen w-full overflow-hidden bg-transparent text-foreground">
        {!navigationOpen && (
          <button
            ref={menuButtonRef}
            type="button"
            aria-label="Open navigation"
            aria-expanded="false"
            aria-controls="console-navigation"
            onClick={() => setNavigationOpen(true)}
            className="navigation-toggle fixed left-4 top-5 z-[70] flex h-10 w-10 flex-col items-center justify-center gap-[5px] rounded-lg border border-primary/25 bg-sidebar/90 px-2.5 shadow-[0_12px_34px_rgba(0,0,0,0.32)] backdrop-blur-xl transition-[border-color,background-color,box-shadow] duration-200 hover:border-primary/55 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          >
            <span className="h-0.5 w-full rounded-full bg-primary transition-transform duration-200" />
            <span className="h-0.5 w-full rounded-full bg-primary transition-[opacity,transform] duration-200" />
            <span className="h-0.5 w-full rounded-full bg-primary transition-transform duration-200" />
          </button>
        )}

        <button
          type="button"
          aria-label="Toggle terminal"
          title="Toggle terminal (Ctrl+`)"
          onClick={() => setTerminalOpen((current) => !current)}
          className={cn(
            'fixed right-4 top-4 z-[70] flex h-12 w-12 items-center justify-center rounded-lg border shadow-[0_12px_34px_rgba(0,0,0,0.32)] backdrop-blur-xl transition-[border-color,background-color,box-shadow] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60',
            terminalOpen
              ? 'border-primary/55 bg-accent text-primary'
              : 'border-primary/25 bg-sidebar/90 text-muted-foreground hover:border-primary/55 hover:bg-accent hover:text-foreground'
          )}
        >
          <AppWindowMac className="h-6 w-6" />
        </button>

        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-[#01040a]/55 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
          <DialogPrimitive.Content
            id="console-navigation"
            aria-describedby={undefined}
            onCloseAutoFocus={(event) => {
              event.preventDefault();
              menuButtonRef.current?.focus();
            }}
            className="fixed inset-y-0 left-0 z-[60] flex w-[17rem] flex-col justify-between border-r border-sidebar-border bg-sidebar/97 shadow-[24px_0_80px_rgba(0,0,0,0.48)] backdrop-blur-xl duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left focus:outline-none"
          >
            <DialogPrimitive.Title className="sr-only">MARM Console navigation</DialogPrimitive.Title>
            <DialogPrimitive.Close asChild>
              <button
                type="button"
                aria-label="Close navigation"
                aria-expanded="true"
                aria-controls="console-navigation"
                className="navigation-toggle fixed left-4 top-5 z-[70] flex h-10 w-10 flex-col items-center justify-center gap-[5px] rounded-lg border border-primary/55 bg-accent px-2.5 shadow-[0_12px_34px_rgba(0,0,0,0.32)] transition-[border-color,background-color,box-shadow] duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              >
                <span className="h-0.5 w-full rounded-full bg-primary transition-transform duration-200" />
                <span className="h-0.5 w-full rounded-full bg-primary transition-[opacity,transform] duration-200" />
                <span className="h-0.5 w-full rounded-full bg-primary transition-transform duration-200" />
              </button>
            </DialogPrimitive.Close>
            <div>
              <div className="flex h-20 items-center border-b border-sidebar-border pl-[4.5rem] pr-5">
                <div className="min-w-0">
                  <div className="font-mono text-[13px] font-bold tracking-[-0.02em] text-primary-highlight">MARM CONSOLE</div>
                  <div className="mt-0.5 text-[9px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">Local intelligence</div>
                </div>
              </div>

              <nav className="space-y-1 p-3 text-sm font-medium" aria-label="Primary navigation">
                {navItems.map((item) => {
                  const active = location === item.href || (item.href !== '/' && location.startsWith(item.href));
                  return (
                    <Link
                      key={item.name}
                      href={item.href}
                      onClick={() => setNavigationOpen(false)}
                      className={cn(
                        'group relative flex h-10 items-center rounded-lg border px-3 transition-[color,background-color,border-color,box-shadow] duration-200',
                        active
                          ? 'border-primary/25 bg-primary/[0.09] text-primary-highlight shadow-[inset_3px_0_0_var(--primary)]'
                          : 'border-transparent text-muted-foreground hover:border-border/70 hover:bg-muted/60 hover:text-foreground'
                      )}
                    >
                      <item.icon className={cn('mr-3 h-4 w-4 transition-colors', active ? 'text-primary' : 'text-muted-foreground group-hover:text-foreground')} />
                      <span className="truncate">{item.name}</span>
                      <ChevronRight className={cn('ml-auto h-3.5 w-3.5 transition-all', active ? 'opacity-70' : '-translate-x-1 opacity-0 group-hover:translate-x-0 group-hover:opacity-50')} />
                    </Link>
                  );
                })}
              </nav>
            </div>

            <div className="border-t border-sidebar-border p-3">
              <div className="mb-3 px-3 pt-1">
                <div className="mb-3 flex items-center justify-between text-[10px] font-semibold uppercase tracking-[0.13em] text-muted-foreground">
                  <span>Accent theme</span>
                  <span className="font-mono normal-case tracking-normal text-primary-highlight">{ACCENT_THEMES.find((theme) => theme.id === accentTheme)?.label}</span>
                </div>
                <div className="flex items-center gap-2" role="group" aria-label="Accent theme">
                  {ACCENT_THEMES.map((theme) => (
                    <button
                      key={theme.id}
                      type="button"
                      title={theme.label + ' theme'}
                      aria-label={theme.label + ' theme'}
                      aria-pressed={accentTheme === theme.id}
                      onClick={() => setAccentTheme(theme.id)}
                      className="theme-swatch h-6 w-6 rounded-full border-2 border-transparent transition-[transform,box-shadow] duration-150 hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/60"
                      style={{ backgroundColor: theme.color, color: theme.color }}
                    />
                  ))}
                </div>
              </div>

              <div className="mb-2 flex items-center justify-between px-3 py-2 text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                <span>Server</span>
                <span className="font-mono normal-case tracking-normal">{data?.mcp_status?.latency_ms !== undefined ? data.mcp_status.latency_ms.toFixed(1) + ' ms' : '—'}</span>
              </div>
              <button
                onClick={() => {
                  setNavigationOpen(false);
                  setSettingsOpen(true);
                }}
                className="group flex w-full items-center justify-between rounded-lg border border-transparent px-3 py-2.5 text-sm text-muted-foreground transition-colors hover:border-border/70 hover:bg-muted/60"
              >
                <div className="flex items-center gap-2">
                  <Settings className="h-4 w-4" />
                  <span>Settings</span>
                </div>
                <div className="flex items-center gap-1.5" title={statusText}>
                  <span className="font-mono text-[10px] uppercase tracking-wide">{statusText}</span>
                  <div className="relative flex h-2 w-2">
                    <span className={cn('relative inline-flex h-2 w-2 rounded-full', statusColor, statusPulse && 'status-pulse')} />
                  </div>
                </div>
              </button>
            </div>
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>

        <main className="app-main flex h-full flex-1 flex-col overflow-hidden">
          {children}
        </main>

        <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
        <TerminalDock open={terminalOpen} onClose={() => setTerminalOpen(false)} />
      </div>
    </DialogPrimitive.Root>
  );
}
