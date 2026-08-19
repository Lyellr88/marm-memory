import { useState } from 'react';
import { Link, useLocation } from 'wouter';
import { useOverview, isAuthError } from '@/hooks/use-marm-queries';
import { SettingsDialog } from './SettingsDialog';
import { Settings, Database, Activity, Network, FolderCode, TerminalSquare } from 'lucide-react';
import { cn } from '@/components/ui/core';

export function Shell({ children }: { children: React.ReactNode }) {
  const [location] = useLocation();
  const [settingsOpen, setSettingsOpen] = useState(false);
  
  const { data, error, isFetching } = useOverview();

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
    statusColor = 'bg-primary';
    statusText = 'Connected';
    statusPulse = true;
  }

  const navItems = [
    { name: 'Overview', href: '/', icon: Activity },
    { name: 'Memories', href: '/memory', icon: Database },
    { name: 'Knowledge Graph', href: '/knowledge', icon: Network },
    { name: 'Indexed Projects', href: '/projects', icon: FolderCode },
  ];

  return (
    <div className="flex h-screen w-full bg-background text-foreground overflow-hidden">
      {/* Sidebar */}
      <div className="w-64 border-r bg-sidebar flex flex-col justify-between shrink-0">
        <div>
          <div className="h-14 flex items-center px-6 border-b font-mono font-bold text-primary tracking-tight">
            <TerminalSquare className="w-5 h-5 mr-2" />
            MARM CONSOLE
          </div>
          <nav className="p-4 space-y-1 text-sm font-medium">
            {navItems.map((item) => {
              const active = location === item.href || (item.href !== '/' && location.startsWith(item.href));
              return (
                <Link
                  key={item.name}
                  href={item.href}
                  className={cn(
                    "flex items-center px-3 py-2 rounded-md transition-colors",
                    active ? "bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  )}
                >
                  <item.icon className="w-4 h-4 mr-3" />
                  {item.name}
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="p-4 border-t border-sidebar-border">
          <button
            onClick={() => setSettingsOpen(true)}
            className="w-full flex items-center justify-between px-3 py-2 rounded-md hover:bg-muted transition-colors text-sm text-muted-foreground group"
          >
            <div className="flex items-center gap-2">
              <Settings className="w-4 h-4" />
              <span>Settings</span>
            </div>
            <div className="flex items-center gap-1.5" title={statusText}>
              <div className="relative flex h-2 w-2">
                {statusPulse && (
                  <span className={cn("animate-ping absolute inline-flex h-full w-full rounded-full opacity-75", statusColor)}></span>
                )}
                <span className={cn("relative inline-flex rounded-full h-2 w-2", statusColor)}></span>
              </div>
            </div>
          </button>
        </div>
      </div>

      {/* Main Content */}
      <main className="flex-1 flex flex-col h-full overflow-hidden">
        {children}
      </main>

      <SettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} />
    </div>
  );
}
