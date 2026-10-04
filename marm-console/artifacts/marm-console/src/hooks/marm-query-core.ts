import { useMarmClient } from '@/lib/use-marm-client';
import { useConnection } from '@/lib/marm-connection';
import type {
  MemoryListParams, MemoryId, LogListParams, ConceptSearchParams, ConceptGraphParams, ManualSnippetParams, ManualAgentCommandParams
} from '@/lib/marm-types';
import { MarmApiError } from '@/lib/marm-api';

export const queryKeys = {
  overview: (baseUrl: string) => ['overview', baseUrl],
  filters: (baseUrl: string) => ['filters', baseUrl],
  memories: (baseUrl: string, params?: MemoryListParams) => ['memories', baseUrl, params],
  memory: (baseUrl: string, id: MemoryId) => ['memory', baseUrl, id],
  sessions: (baseUrl: string) => ['sessions', baseUrl],
  distillPending: (baseUrl: string, session?: string | null) => ['distill-pending', baseUrl, session ?? null],
  logs: (baseUrl: string, params?: LogListParams) => ['logs', baseUrl, params],
  notebook: (baseUrl: string, params?: any) => ['notebook', baseUrl, params],
  summary: (baseUrl: string, session: string) => ['summary', baseUrl, session],
  compaction: (baseUrl: string) => ['compaction', baseUrl],
  conceptsSummary: (baseUrl: string) => ['conceptsSummary', baseUrl],
  conceptsGraph: (baseUrl: string, params?: ConceptGraphParams) => ['conceptsGraph', baseUrl, params],
  conceptsGraphVersion: (baseUrl: string) => ['conceptsGraphVersion', baseUrl],
  conceptsSearch: (baseUrl: string, params?: ConceptSearchParams) => ['conceptsSearch', baseUrl, params],
  concept: (baseUrl: string, id: number) => ['concept', baseUrl, id],
  neighborhood: (baseUrl: string, id: number, params?: any) => ['neighborhood', baseUrl, id, params],
  conceptBuild: (baseUrl: string, id: string) => ['conceptBuild', baseUrl, id],
  conceptBuilds: (baseUrl: string) => ['conceptBuilds', baseUrl],
  duplicates: (baseUrl: string) => ['duplicates', baseUrl],
  runtimeSettings: (baseUrl: string) => ['runtimeSettings', baseUrl],
  projects: (baseUrl: string) => ['projects', baseUrl],
  indexJob: (baseUrl: string, id: string) => ['indexJob', baseUrl, id],
  projectStatus: (baseUrl: string, project: string) => ['projectStatus', baseUrl, project],
  projectArchitecture: (baseUrl: string, project: string) => ['projectArchitecture', baseUrl, project],
  projectCodeUnits: (baseUrl: string, project: string) => ['projectCodeUnits', baseUrl, project],
  projectGraph: (baseUrl: string, project: string) => ['projectGraph', baseUrl, project],
  projectGraphNeighborhood: (baseUrl: string, project: string, nodeId: string) => ['projectGraphNeighborhood', baseUrl, project, nodeId],
  projectCodeUnitEdges: (baseUrl: string, project: string, unit: string) => ['projectCodeUnitEdges', baseUrl, project, unit],
  projectMemoryLinking: (baseUrl: string, project: string) => ['projectMemoryLinking', baseUrl, project],
  projectMemoryLinks: (baseUrl: string, project: string) => ['projectMemoryLinks', baseUrl, project],
  agents: (baseUrl: string, target = '') => ['agents', baseUrl, target],
  agentScope: (baseUrl: string, id: string, scope: string, project: string, target = '') => ['agent-scope', baseUrl, id, scope, project, target],
  docker: (baseUrl: string) => ['docker', baseUrl],
  connectionsOverview: (baseUrl: string) => ['connections-overview', baseUrl],
  setupSettings: (baseUrl: string) => ['setup-settings', baseUrl],
  manualSnippet: (baseUrl: string, params: ManualSnippetParams | null) => ['manual-snippet', baseUrl, params],
  manualAgentCommands: (baseUrl: string, params: ManualAgentCommandParams) => ['manual-agent-commands', baseUrl, params],
  manualCli: (baseUrl: string) => ['manual-cli', baseUrl],
  manualEndpoints: (baseUrl: string) => ['manual-endpoints', baseUrl],
  manualEnv: (baseUrl: string) => ['manual-env', baseUrl],
};

// Global config hook
export function useMarmConfig() {
  const { baseUrl } = useConnection();
  return { baseUrl, client: useMarmClient() };
}

// Check auth errors specifically
export function isAuthError(err: unknown) {
  return err instanceof MarmApiError && (err.status === 401 || err.status === 403);
}
