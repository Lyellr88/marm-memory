import type { ConceptBuildRun } from './concepts';
import type { ProjectSummary } from './projects';

export interface Overview {
  memory: {
    active_memories: number;
    compacted_sources: number;
    pending_compaction: number;
    staged_compaction: number;
    missing_embeddings: number;
    sessions: number;
    log_entries: number;
    notebook_entries: number;
    projects: string[];
    platforms: string[];
  };
  concepts: {
    status: 'unavailable' | 'not_built' | 'ready';
    entities: number;
    relationships: number;
    code_links: number;
    recent_builds: ConceptBuildRun[];
  };
  graph: {
    status: 'disabled' | 'starting' | 'ready' | 'error';
    projects: ProjectSummary[];
  };
  runtime_mode: 'embedded' | 'standalone';
  mcp_status?: McpStatus;
}

export interface McpStatus {
  reachable: boolean;
  version?: string;
  status?: string;
  latency_ms?: number;
  last_checked?: string;
}

export interface Filters {
  sessions: string[];
  projects: string[];
  platforms: string[];
  context_types: string[];
}
