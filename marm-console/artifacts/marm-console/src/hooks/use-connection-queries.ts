import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { SetupSettingValue, AgentScopeName, AgentConfigureBody, AgentRemoveBody, AgentTestBody, AgentTarget, ManualSnippetParams, ManualAgentCommandParams } from '@/lib/marm-types';
import { queryKeys, useMarmConfig } from './marm-query-core';

// --- Connections ---
export function useAgents(target?: AgentTarget) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.agents(baseUrl, target), queryFn: () => client.getAgents(target) });
}

export function useAgentScope(id: string, scope: AgentScopeName, project: string | undefined, enabled = true, target?: AgentTarget) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({
    queryKey: queryKeys.agentScope(baseUrl, id, scope, project ?? '', target),
    queryFn: () => client.getAgentScope(id, scope, project, target),
    enabled,
    retry: false,
  });
}

function useInvalidateAgents() {
  const { baseUrl } = useMarmConfig();
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: queryKeys.agents(baseUrl) });
    qc.invalidateQueries({ queryKey: ['agent-scope', baseUrl] });
    qc.invalidateQueries({ queryKey: queryKeys.connectionsOverview(baseUrl) });
  };
}

export function useConfigureAgent() {
  const { client } = useMarmConfig();
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: AgentConfigureBody }) => client.configureAgent(id, body),
    onSuccess: (_data, variables) => {
      if (!variables.body.dry_run) invalidate();
    },
  });
}

export function useRemoveAgent() {
  const { client } = useMarmConfig();
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: AgentRemoveBody }) => client.removeAgent(id, body),
    onSuccess: (_data, variables) => {
      if (!variables.body.dry_run) invalidate();
    },
  });
}

export function useTestAgent() {
  const { client } = useMarmConfig();
  return useMutation({ mutationFn: ({ id, body }: { id: string; body: AgentTestBody }) => client.testAgent(id, body) });
}

export function useInstallAgentSkill() {
  const { client } = useMarmConfig();
  const invalidate = useInvalidateAgents();
  return useMutation({
    mutationFn: (id: string) => client.installAgentSkill(id),
    onSuccess: invalidate,
  });
}

export function useConnectionsOverview() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.connectionsOverview(baseUrl), queryFn: client.getConnectionsOverview, refetchInterval: 10000, retry: false });
}

export function useSetupSettings() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.setupSettings(baseUrl), queryFn: client.getSetupSettings, retry: false });
}

export function useUpdateSetupSettings() {
  const { baseUrl, client } = useMarmConfig();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (values: Record<string, SetupSettingValue>) => client.updateSetupSettings(values),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.setupSettings(baseUrl) });
      qc.invalidateQueries({ queryKey: queryKeys.connectionsOverview(baseUrl) });
    },
  });
}

export function useManualSnippet(params: ManualSnippetParams | null) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.manualSnippet(baseUrl, params), queryFn: () => client.getManualSnippet(params as ManualSnippetParams), enabled: params !== null, retry: false });
}

export function useManualAgentCommands(params: ManualAgentCommandParams) {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.manualAgentCommands(baseUrl, params), queryFn: () => client.getManualAgentCommands(params), retry: false });
}

export function useManualCli() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.manualCli(baseUrl), queryFn: client.getManualCli, staleTime: 5 * 60_000, retry: false });
}

export function useManualEndpoints() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.manualEndpoints(baseUrl), queryFn: client.getManualEndpoints, staleTime: 30_000, retry: false });
}

export function useManualEnv() {
  const { baseUrl, client } = useMarmConfig();
  return useQuery({ queryKey: queryKeys.manualEnv(baseUrl), queryFn: client.getManualEnv, staleTime: 5 * 60_000, retry: false });
}
