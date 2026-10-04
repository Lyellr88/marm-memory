export interface DockerConfig {
  port: number;
  tag: string;
  data_dir: string;
  repos: string[];
  memory: string | null;
  cpus: string | null;
  expose_network: boolean;
  profile: string;
  rate_limit_rpm: number | null;
}

export interface DockerEngine {
  available: boolean;
  daemon: boolean;
  version: string | null;
  reason: string | null;
}

export interface DockerPortBinding {
  HostIp?: string;
  HostPort?: string;
}

export interface DockerContainer {
  detail?: string;
  state: string;
  name: string;
  health?: string;
  image?: string;
  image_id?: string;
  profile?: string;
  ports?: Record<string, DockerPortBinding[] | null>;
  restart_policy?: string;
  mounts?: Array<{ source: string | null; destination: string | null }>;
}

export interface DockerOverview {
  engine: DockerEngine;
  in_container: boolean;
  read_only_reason: string | null;
  container: DockerContainer;
  config: DockerConfig;
  url: string;
}

export interface DockerJob {
  job_id: string;
  kind: string;
  status: 'queued' | 'running' | 'done' | 'error';
  seconds?: number;
  detail?: string;
}

export interface DockerLogs {
  lines: string[];
}

export interface DockerCompose {
  path: string;
  exists: boolean;
  yaml: string;
  command: string;
}

export interface DockerComposeWritten {
  path: string;
  command: string;
  backup_path?: string | null;
}
