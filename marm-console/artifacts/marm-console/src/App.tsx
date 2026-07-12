import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Route, Switch, Router as WouterRouter } from 'wouter';
import { ConnectionProvider } from '@/lib/marm-connection';

import { Shell } from '@/components/layout/Shell';
import { OverviewPage } from '@/pages/Overview';
import { MemoryPage } from '@/pages/Memory';
import { KnowledgePage } from '@/pages/Knowledge';
import { ProjectsPage } from '@/pages/Projects';
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
        <Route component={NotFound} />
      </Switch>
    </Shell>
  );
}

function App() {
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
