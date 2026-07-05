export type GitProvider = 'github' | 'gitlab';
export type AgentStatus = 'online' | 'offline';
export type OperationStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export type ConfigSummary = {
  default_agent: string;
  defaults: {
    image: string;
  };
  github: {
    token_env: string;
    has_token: boolean;
  };
  gitlab: {
    token_env: string;
    api_url: string;
    ssh_host: string;
    has_token: boolean;
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
    git_ssh_host: string;
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
  git_ssh_host: string;
  template: string;
  instance: string;
  alias?: string | null;
  ssh_host: string;
  port: number;
  status?: string | null;
  ssh_command: string;
  raw_ssh_command: string;
  trae_url: string;
  has_local_alias: boolean;
};

export type Operation = {
  id: string;
  agent_id: string;
  alias: string;
  repo: string;
  provider: GitProvider;
  git_ssh_host?: string | null;
  template: string;
  instance: string;
  status: OperationStatus;
  stage: string;
  error?: string | null;
  created_at: number;
  _polling?: boolean;
};

export type InstanceRow = {
  key: string;
  agent_id: string;
  repo: string;
  provider: GitProvider;
  git_ssh_host?: string | null;
  template: string;
  instance: string;
  alias?: string | null;
  id?: string;
  ssh_host?: string;
  port?: number;
  status?: string | null;
  stage?: string;
  error?: string | null;
  raw_ssh_command?: string;
  trae_url?: string;
  kind: 'codespace' | 'operation';
};

export type FilterState = {
  agent: string;
  status: string;
  sort: 'agent' | 'repo' | 'template' | 'instance' | 'alias' | 'status';
};

export type CreateForm = {
  agent: string;
  repo: string;
  provider: GitProvider;
  git_ssh_host: string;
  template: string;
  instance: string;
  image: string;
  envText: string;
};

export type Toast = {
  id: number;
  message: string;
  tone: 'success' | 'warning' | 'danger';
};
