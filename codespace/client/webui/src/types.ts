export type GitProvider = 'github' | 'gitlab';
export type AgentStatus = 'online' | 'offline';
export type OperationStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export type ConfigSummary = {
  default_agent: string;
  defaults: {
    image: string;
  };
  agents: Array<{
    id: string;
    agent_url: string;
    ssh_host: string;
    ssh_proxy_host?: string | null;
    ssh_proxy: boolean;
  }>;
  templates: Array<{
    id: string;
    description?: string | null;
    agent?: string | null;
    provider: GitProvider;
    repo: string;
    image?: string | null;
  }>;
};

export type Dashboard = {
  agents: Agent[];
  codespaces: Codespace[];
  operations: Operation[];
};

export type ClearOperationsResponse = {
  operations: Operation[];
};

export type TokenStatusResponse = Record<GitProvider, { has_token: boolean }>;

export type Agent = {
  id: string;
  agent_url: string;
  ssh_host: string;
  ssh_proxy_host?: string | null;
  ssh_proxy: boolean;
  status: AgentStatus;
  error?: string | null;
  codespace_count: number;
};

export type Codespace = {
  agent_id: string;
  id: string;
  repo: string;
  provider: GitProvider;
  template: string;
  instance: string;
  alias?: string | null;
  ssh_host: string;
  port: number;
  status?: string | null;
  raw_ssh_command: string;
  trae_url: string;
};

export type Operation = {
  id: string;
  agent_id: string;
  alias: string;
  repo: string;
  provider: GitProvider;
  template: string;
  instance: string;
  status: OperationStatus;
  stage: string;
  error?: string | null;
  created_at: number;
  updated_at: number;
};

/**
 * One card in the connection-first grid: a ready codespace or an in-flight
 * create operation. Connection fields are only present for `kind: 'codespace'`.
 */
export type InstanceCard = {
  key: string;
  agent_id: string;
  repo: string;
  provider: GitProvider;
  template: string;
  instance: string;
  alias?: string | null;
  id?: string;
  status?: string | null;
  stage?: string;
  error?: string | null;
  raw_ssh_command?: string;
  trae_url?: string;
  kind: 'codespace' | 'operation';
};

export type CreateForm = {
  agent: string;
  repo: string;
  provider: GitProvider;
  template: string;
  instance: string;
  image: string;
};

export type Toast = {
  id: number;
  message: string;
  tone: 'success' | 'warning' | 'danger';
};
