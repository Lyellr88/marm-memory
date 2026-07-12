import { useMemo } from 'react';
import { createMarmClient, type MarmClient } from './marm-api';
import { useConnection } from './marm-connection';

// Returns a MarmClient bound to the currently configured base URL / API key.
// Use this inside React Query hooks, e.g.:
//
//   const client = useMarmClient();
//   const { data } = useQuery({ queryKey: ['overview', client.baseUrl], queryFn: client.getOverview });
export function useMarmClient(): MarmClient {
  const { baseUrl, apiKey } = useConnection();
  return useMemo(() => createMarmClient({ baseUrl, apiKey }), [baseUrl, apiKey]);
}
