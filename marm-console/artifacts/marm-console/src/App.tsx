import { useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Route, Switch, Router as WouterRouter } from 'wouter';
import { ConnectionProvider } from '@/lib/marm-connection';

import { Shell } from '@/components/layout/Shell';
import { OverviewPage } from '@/pages/Overview';
import { MemoryPage } from '@/pages/Memory';
import { KnowledgePage } from '@/pages/Knowledge';
import { ProjectsPage } from '@/pages/Projects';
import { ExplorerPage } from '@/pages/Explorer';
import { SystemPage } from '@/pages/System';
import NotFound from '@/pages/not-found';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      refetchOnWindowFocus: false,
      staleTime: 5_000,
    },
  },
});

function Router() {
  return (
    <Shell>
      <Switch>
        <Route path="/" component={OverviewPage} />
        <Route path="/memory" component={MemoryPage} />
        <Route path="/knowledge" component={KnowledgePage} />
        <Route path="/projects" component={ProjectsPage} />
        <Route path="/explorer" component={ExplorerPage} />
        <Route path="/explorer/:name" component={ExplorerPage} />
        <Route path="/system" component={SystemPage} />
        <Route component={NotFound} />
      </Switch>
    </Shell>
  );
}

function useConsoleBootstrap(): boolean {
  const [ready, setReady] = useState(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    return !params.get('marm-bootstrap');
  });

  useEffect(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    const token = params.get('marm-bootstrap');
    if (!token) return;

    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
    void fetch('/api/auth/bootstrap', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    }).finally(() => setReady(true));
  }, []);

  return ready;
}

function App() {
  const ready = useConsoleBootstrap();

  if (!ready) return null;

  return (
    <QueryClientProvider client={queryClient}>
      <ConnectionProvider>
        <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, '')}>
          <Router />
        </WouterRouter>
      </ConnectionProvider>
    </QueryClientProvider>
  );
}

export default App;
