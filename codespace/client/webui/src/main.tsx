import '@mantine/core/styles.css';
import './styles.css';

import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Card,
  Checkbox,
  Code,
  Container,
  Divider,
  Flex,
  Grid,
  Group,
  MantineProvider,
  Modal,
  NativeSelect,
  NumberFormatter,
  Paper,
  Progress,
  ScrollArea,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
} from '@mantine/core';
import { IconRefresh, IconX } from '@tabler/icons-react';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';

type AgentStatus = 'online' | 'offline';
type OperationStatus = 'queued' | 'running' | 'succeeded' | 'failed';

type ConfigSummary = {
  default_agent: string;
  defaults: {
    image: string;
    extra_repos: string[];
  };
  github: {
    token_env: string;
    has_token: boolean;
    inline_token: boolean;
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
    repo: string;
    alias?: string | null;
    image?: string | null;
    extra_repos?: string[] | null;
  }>;
};

type Dashboard = {
  agents: Agent[];
  codespaces: Codespace[];
  operations: Operation[];
};

type ClearOperationsResponse = {
  operations: Operation[];
};

type Agent = {
  id: string;
  agent_url: string;
  ssh_host: string;
  ssh_proxy_host?: string | null;
  ssh_proxy: boolean;
  status: AgentStatus;
  error?: string | null;
  codespace_count: number;
};

type Codespace = {
  agent_id: string;
  id: string;
  repo: string;
  workspace: string;
  alias?: string | null;
  ssh_host: string;
  port: number;
  status?: string | null;
  ssh_command: string;
  raw_ssh_command: string;
  trae_url: string;
  has_local_alias: boolean;
};

type Operation = {
  id: string;
  agent_id: string;
  alias: string;
  repo: string;
  status: OperationStatus;
  stage: string;
  error?: string | null;
  created_at: number;
  _polling?: boolean;
};

type FilterState = {
  agent: string;
  status: string;
  search: string;
  sort: keyof Codespace | 'agent';
};

type CreateForm = {
  agent: string;
  repo: string;
  alias: string;
  image: string;
  extraRepos: string;
  autoAlias: boolean;
};

type Toast = {
  id: number;
  message: string;
  tone: 'success' | 'warning' | 'danger';
};

const emptyDashboard: Dashboard = { agents: [], codespaces: [], operations: [] };
const defaultFilter: FilterState = { agent: 'all', status: 'all', search: '', sort: 'agent' };

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    },
    ...options,
  });
  const body = response.headers.get('content-type')?.includes('application/json')
    ? await response.json()
    : {};
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body as T;
}

function repoName(repo: string): string {
  return repo.includes('/') ? repo.split('/').at(-1) || repo : repo;
}

function defaultAlias(agent: string, repo: string): string {
  return agent && repo ? `${agent}-${repoName(repo)}` : '';
}

function normalizeStatus(status?: string | null): string {
  return String(status || 'unknown').toLowerCase();
}

function isBusyOperation(op: Operation): boolean {
  return op.status === 'queued' || op.status === 'running';
}

function operationProgress(status: OperationStatus): number {
  if (status === 'queued') return 12;
  if (status === 'running') return 58;
  return status === 'succeeded' || status === 'failed' ? 100 : 0;
}

function statusColor(status?: string | null): string {
  const normalized = normalizeStatus(status);
  if (['online', 'running', 'succeeded'].includes(normalized)) return 'green';
  if (['offline', 'failed'].includes(normalized)) return 'red';
  if (normalized === 'queued') return 'yellow';
  return 'gray';
}

function formatTime(timestamp: number | null): string {
  return timestamp ? new Date(timestamp).toLocaleTimeString() : '尚未刷新';
}

function App() {
  const [config, setConfig] = useState<ConfigSummary | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard>(emptyDashboard);
  const [operations, setOperations] = useState<Map<string, Operation>>(new Map());
  const [filter, setFilter] = useState<FilterState>(defaultFilter);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [form, setForm] = useState<CreateForm>({
    agent: '',
    repo: '',
    alias: '',
    image: '',
    extraRepos: '',
    autoAlias: true,
  });
  const autoRefreshRef = useRef<number | null>(null);
  const operationRef = useRef(operations);

  useEffect(() => {
    operationRef.current = operations;
  }, [operations]);

  const showToast = useCallback((message: string, tone: Toast['tone'] = 'success') => {
    const id = Date.now() + Math.random();
    setToasts((items) => [...items, { id, message, tone }]);
    window.setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 3500);
  }, []);

  const pollOperation = useCallback(
    async (id: string) => {
      const op = operationRef.current.get(id);
      if (!op || op._polling) return;
      setOperations((current) => {
        const next = new Map(current);
        const existing = next.get(id);
        if (existing) next.set(id, { ...existing, _polling: true });
        return next;
      });
      while (true) {
        const previous = operationRef.current.get(id) || op;
        const latest = await request<Operation>(`/api/operations/${encodeURIComponent(id)}`).catch(
          (requestError: Error) => ({
            ...previous,
            status: 'failed' as OperationStatus,
            stage: 'polling failed',
            error: requestError.message,
          }),
        );
        setOperations((current) => new Map(current).set(id, { ...latest, _polling: true }));
        if (latest.status === 'succeeded') {
          showToast(`Codespace ready: ${latest.alias}`);
          setOperations((current) => new Map(current).set(id, { ...latest, _polling: false }));
          await refreshDashboard();
          return;
        }
        if (latest.status === 'failed') {
          showToast(`Operation failed: ${latest.alias}`, 'danger');
          setOperations((current) => new Map(current).set(id, { ...latest, _polling: false }));
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
      }
    },
    [showToast],
  );

  const refreshDashboard = useCallback(async () => {
    setRefreshing(true);
    try {
      setError(null);
      const result = await request<Dashboard>('/api/dashboard');
      setDashboard(result);
      setLastUpdated(Date.now());
      setOperations((current) => {
        const next = new Map(current);
        for (const op of result.operations || []) next.set(op.id, op);
        return next;
      });
      for (const op of operationRef.current.values()) if (isBusyOperation(op)) void pollOperation(op.id);
    } catch (refreshError) {
      setError((refreshError as Error).message);
    } finally {
      setRefreshing(false);
    }
  }, [pollOperation]);

  const clearOperations = useCallback(async () => {
    try {
      const result = await request<ClearOperationsResponse>('/api/operations', { method: 'DELETE' });
      setOperations(new Map(result.operations.map((op) => [op.id, op])));
    } catch (clearError) {
      setError((clearError as Error).message);
    }
  }, []);

  useEffect(() => {
    async function loadAll() {
      try {
        setError(null);
        const loadedConfig = await request<ConfigSummary>('/api/config');
        setConfig(loadedConfig);
        await refreshDashboard();
      } catch (loadError) {
        setError((loadError as Error).message);
      }
    }
    void loadAll();
  }, [refreshDashboard]);

  useEffect(() => {
    if (autoRefreshRef.current) window.clearInterval(autoRefreshRef.current);
    if (!autoRefresh) return;
    autoRefreshRef.current = window.setInterval(() => void refreshDashboard(), 15000);
    return () => {
      if (autoRefreshRef.current) window.clearInterval(autoRefreshRef.current);
    };
  }, [autoRefresh, refreshDashboard]);

  const filteredCodespaces = useMemo(() => {
    const search = filter.search.toLowerCase();
    return dashboard.codespaces
      .filter((cs) => {
        const status = normalizeStatus(cs.status);
        return (
          (filter.agent === 'all' || cs.agent_id === filter.agent) &&
          (filter.status === 'all' || status === filter.status || (filter.status === 'unknown' && !cs.status)) &&
          (!search ||
            [cs.repo, cs.workspace, cs.alias, cs.id, cs.agent_id, cs.status]
              .filter(Boolean)
              .some((value) => String(value).toLowerCase().includes(search)))
        );
      })
      .sort((left, right) => {
        const leftValue = filter.sort === 'agent' ? left.agent_id : left[filter.sort];
        const rightValue = filter.sort === 'agent' ? right.agent_id : right[filter.sort];
        return String(leftValue || '').localeCompare(String(rightValue || ''));
      });
  }, [dashboard.codespaces, filter]);

  function updateForm(patch: Partial<CreateForm>) {
    setForm((current) => {
      const next = { ...current, ...patch };
      if (next.autoAlias) next.alias = defaultAlias(next.agent, next.repo.trim());
      return next;
    });
  }

  function openCreate(templateId?: string) {
    if (!config) return;
    const template = config.templates.find((item) => item.id === templateId);
    const agent = template?.agent || (filter.agent !== 'all' ? filter.agent : config.default_agent);
    const repo = template?.repo || '';
    const autoAlias = !template?.alias;
    const nextForm: CreateForm = {
      agent,
      repo,
      alias: template?.alias || defaultAlias(agent, repo),
      image: template?.image || config.defaults.image,
      extraRepos: (template?.extra_repos ?? config.defaults.extra_repos).join('\n'),
      autoAlias,
    };
    setForm(nextForm);
    setCreateError(null);
    setCreateOpen(true);
  }

  async function submitCreate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!config) return;
    setSubmitting(true);
    try {
      const payload = {
        repo: form.repo.trim(),
        alias: form.alias.trim(),
        image: form.image.trim(),
        extra_repos: form.extraRepos
          .split(/\n|,/)
          .map((item) => item.trim())
          .filter(Boolean),
      };
      const result = await request<{ operation_id: string }>(
        `/api/agents/${encodeURIComponent(form.agent)}/codespaces`,
        { method: 'POST', body: JSON.stringify(payload) },
      );
      setCreateOpen(false);
      const operation: Operation = {
        id: result.operation_id,
        status: 'queued',
        stage: 'queued',
        ...payload,
        agent_id: form.agent,
        created_at: Date.now() / 1000,
      };
      setOperations((current) => new Map(current).set(result.operation_id, operation));
      showToast(`Create operation started: ${payload.alias}`);
      void pollOperation(result.operation_id);
    } catch (submitError) {
      const message = (submitError as Error).message;
      setCreateError(message);
      showToast(message, 'danger');
    } finally {
      setSubmitting(false);
    }
  }

  async function deleteCodespace(cs: Codespace, purge: boolean) {
    if (!window.confirm(purge ? '确认删除并 purge workspace？' : '确认删除 codespace？')) return;
    try {
      const result = await request<{ warning?: string | null }>(
        `/api/agents/${encodeURIComponent(cs.agent_id)}/codespaces/${encodeURIComponent(cs.id)}?repo=${encodeURIComponent(cs.repo)}${purge ? '&purge=true' : ''}`,
        { method: 'DELETE' },
      );
      setError(result.warning || null);
      showToast(result.warning || 'Codespace deleted', result.warning ? 'warning' : 'success');
      await refreshDashboard();
    } catch (deleteError) {
      setError((deleteError as Error).message);
    }
  }

  const runningOps = [...operations.values()].filter(isBusyOperation).length;
  const selectedAgent = config?.agents.find((agent) => agent.id === form.agent);

  return (
    <MantineProvider defaultColorScheme="light" forceColorScheme="light">
      <Box className="app-shell">
        <header className="topbar">
          <Group gap="sm" wrap="nowrap">
            <Title order={1} size="h4">Codespace</Title>
            <Badge variant="light" color={config?.github.has_token ? 'gray' : 'yellow'}>
              {config ? `${config.default_agent} · ${config.github.has_token ? 'token ok' : 'no token'}` : '加载配置中...'}
            </Badge>
          </Group>
          <Group gap="xs" className="toolbar">
            <Select
              placeholder="template..."
              data={config?.templates.map((item) => ({ value: item.id, label: `${item.id} · ${item.repo}` })) || []}
              className="toolbar-template"
              size="xs"
              onChange={(value) => value && openCreate(value)}
              searchable
            />
            <Button size="xs" variant="default" onClick={() => openCreate()}>Blank</Button>
            <Button size="xs" variant="default" leftSection={<IconRefresh size={14} />} loading={refreshing} onClick={() => void refreshDashboard()}>
              Refresh
            </Button>
            <Button size="xs" onClick={() => openCreate()}>Create</Button>
          </Group>
        </header>

        <Container fluid className="workbench">
          <Stack gap="sm" className="main-pane">
            <Grid gap="xs" aria-label="Dashboard summary">
              <StatCard label="codespaces" value={dashboard.codespaces.length} />
              <StatCard label="online" value={dashboard.agents.filter((agent) => agent.status === 'online').length} />
              <StatCard label="offline" value={dashboard.agents.filter((agent) => agent.status === 'offline').length} />
              <StatCard label="ops" value={runningOps} />
            </Grid>
            {error && <Alert color="yellow">{error}</Alert>}
            <Paper withBorder radius="md" className="panel-card">
              <Group justify="space-between" className="panel-heading">
                <Title order={2} size="h5">Codespaces</Title>
                <Badge variant="light"><NumberFormatter value={filteredCodespaces.length} /></Badge>
              </Group>
              <Flex gap="xs" className="filter-bar-react">
                <Select
                  size="xs"
                  data={[{ value: 'all', label: 'All agents' }, ...dashboard.agents.map((agent) => ({ value: agent.id, label: agent.id }))]}
                  value={filter.agent}
                  onChange={(value) => setFilter((current) => ({ ...current, agent: value || 'all' }))}
                />
                <Select
                  size="xs"
                  data={[
                    { value: 'all', label: 'All status' },
                    { value: 'running', label: 'Running' },
                    { value: 'stopped', label: 'Stopped' },
                    { value: 'unknown', label: 'Unknown' },
                  ]}
                  value={filter.status}
                  onChange={(value) => setFilter((current) => ({ ...current, status: value || 'all' }))}
                />
                <TextInput
                  size="xs"
                  placeholder="repo / workspace / alias / id"
                  value={filter.search}
                  onChange={(event) => setFilter((current) => ({ ...current, search: event.currentTarget.value }))}
                  className="search-input"
                />
                <Select
                  size="xs"
                  data={[
                    { value: 'agent', label: 'Agent' },
                    { value: 'repo', label: 'Repository' },
                    { value: 'workspace', label: 'Workspace' },
                    { value: 'status', label: 'Status' },
                  ]}
                  value={filter.sort}
                  onChange={(value) => setFilter((current) => ({ ...current, sort: (value || 'agent') as FilterState['sort'] }))}
                />
                <Button size="xs" variant="default" onClick={() => setFilter(defaultFilter)}>Clear</Button>
              </Flex>
              <ScrollArea>
                <Table striped highlightOnHover verticalSpacing="xs" className="codespace-table">
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Agent</Table.Th>
                      <Table.Th>Repo</Table.Th>
                      <Table.Th>Workspace</Table.Th>
                      <Table.Th>Alias</Table.Th>
                      <Table.Th>Status</Table.Th>
                      <Table.Th>SSH</Table.Th>
                      <Table.Th ta="right">Actions</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {filteredCodespaces.map((cs) => (
                      <Table.Tr key={`${cs.agent_id}-${cs.id}`}>
                        <Table.Td>
                          <Button size="compact-xs" variant="subtle" px={0} onClick={() => setFilter((current) => ({ ...current, agent: cs.agent_id }))}>
                            {cs.agent_id}
                          </Button>
                        </Table.Td>
                        <Table.Td><Text fw={600}>{cs.repo}</Text></Table.Td>
                        <Table.Td>{cs.workspace}</Table.Td>
                        <Table.Td>{cs.alias ? <Code>{cs.alias}</Code> : <Text c="dimmed" size="xs">无本地 alias</Text>}</Table.Td>
                        <Table.Td><Badge color={statusColor(cs.status)} variant="light">{cs.status || 'unknown'}</Badge></Table.Td>
                        <Table.Td><Code className="ssh-code">{cs.ssh_command}</Code></Table.Td>
                        <Table.Td>
                          <Group justify="flex-end" gap="xs" wrap="nowrap">
                            <Button size="compact-xs" component="a" href={cs.trae_url}>Trae IDE</Button>
                            <Button size="compact-xs" variant="default" color="red" onClick={() => void deleteCodespace(cs, false)}>Delete</Button>
                            <Button size="compact-xs" color="red" onClick={() => void deleteCodespace(cs, true)}>Purge</Button>
                          </Group>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </ScrollArea>
              {filteredCodespaces.length === 0 && <Text c="dimmed" p="md">暂无 codespace</Text>}
            </Paper>
          </Stack>

          <Stack gap="sm" className="side-pane">
            <SidePanel title="Runtime">
              <Group justify="space-between">
                <Stack gap={2}>
                  <Text fw={700} c={config?.github.has_token ? 'green' : 'yellow'}>{config?.github.has_token ? 'Token ready' : 'Token missing'}</Text>
                  <Text size="xs" c="dimmed">{config?.github.has_token ? config.github.token_env : `set ${config?.github.token_env || 'GITHUB_TOKEN'}`}</Text>
                </Stack>
                <Checkbox label="auto" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.currentTarget.checked)} />
              </Group>
              <Divider my="sm" />
              <Text size="xs" c="dimmed">Last updated: {formatTime(lastUpdated)}</Text>
            </SidePanel>

            <SidePanel title="Templates">
              <Stack gap="xs">
                {config?.templates.length ? config.templates.map((template) => (
                  <Card key={template.id} withBorder padding="sm" radius="md">
                    <Group justify="space-between" align="flex-start">
                      <Text fw={700}>{template.id}</Text>
                      <Text size="xs" c="blue">{template.repo}</Text>
                    </Group>
                    {template.description && <Text size="xs" c="dimmed" mt={4}>{template.description}</Text>}
                    <Text size="xs" c="dimmed" mt={6}>{template.agent || config.default_agent}</Text>
                    <Button size="xs" fullWidth mt="xs" onClick={() => openCreate(template.id)}>Create</Button>
                  </Card>
                )) : <Text c="dimmed" size="sm">暂无模板</Text>}
              </Stack>
            </SidePanel>

            <SidePanel title="Agents">
              <Stack gap="xs">
                {dashboard.agents.length ? dashboard.agents.map((agent) => (
                  <Card key={agent.id} withBorder padding="sm" radius="md">
                    <Group justify="space-between" align="flex-start">
                      <Text fw={700}>{agent.id}</Text>
                      <Group gap={4}>
                        {agent.ssh_proxy && <Badge color="grape" variant="light">ssh proxy</Badge>}
                        <Badge color={statusColor(agent.status)} variant="light">{agent.status}</Badge>
                      </Group>
                    </Group>
                    <Text size="xs" c="dimmed" mt={6}>{agent.agent_url}</Text>
                    <Text size="xs" c="dimmed">ssh: {agent.ssh_host}</Text>
                    {agent.ssh_proxy && agent.ssh_proxy_host && (
                      <Text size="xs" c="dimmed">proxy: {agent.ssh_proxy_host}</Text>
                    )}
                    <Text size="xs" c="dimmed">{agent.codespace_count} codespaces</Text>
                    {agent.error && <Alert color="red" mt="xs">{agent.error}</Alert>}
                  </Card>
                )) : <Text c="dimmed" size="sm">暂无 agent 信息</Text>}
              </Stack>
            </SidePanel>

            <SidePanel title="Operations" action={<Button size="compact-xs" variant="default" onClick={() => void clearOperations()}>Clear</Button>}>
              <Stack gap="xs">
                {[...operations.values()].sort((a, b) => b.created_at - a.created_at).map((op) => (
                  <Card key={op.id} withBorder padding="sm" radius="md">
                    <Group justify="space-between" align="flex-start">
                      <Box>
                        <Text fw={700}>{op.alias}</Text>
                        <Text size="xs" c="dimmed">{op.repo} · {op.agent_id}</Text>
                      </Box>
                      <Badge color={statusColor(op.status)} variant="light">{op.status}</Badge>
                    </Group>
                    <Progress mt="xs" size="xs" value={operationProgress(op.status)} color={statusColor(op.status)} />
                    <Text size="xs" c="dimmed" mt={4}>{op.stage}</Text>
                    {op.error && <Alert color="red" mt="xs">{op.error}</Alert>}
                  </Card>
                ))}
                {operations.size === 0 && <Text c="dimmed" size="sm">暂无 operation</Text>}
              </Stack>
            </SidePanel>
          </Stack>
        </Container>

        <Modal opened={createOpen} onClose={() => setCreateOpen(false)} title="Create Codespace" size="lg" centered>
          <form onSubmit={submitCreate}>
            <Stack>
              {createError && <Alert color="red">{createError}</Alert>}
              {config && !config.github.has_token && <Alert color="yellow">创建 codespace 需要 GitHub token。请在启动 Web GUI 前设置 {config.github.token_env}。</Alert>}
              <Grid>
                <Grid.Col span={6}>
                  <Select label="Agent" data={config?.agents.map((agent) => ({ value: agent.id, label: agent.id })) || []} value={form.agent} onChange={(value) => updateForm({ agent: value || '' })} required />
                </Grid.Col>
                <Grid.Col span={6}>
                  <TextInput label="Repo" placeholder="owner/name" value={form.repo} onChange={(event) => updateForm({ repo: event.currentTarget.value })} required />
                </Grid.Col>
                <Grid.Col span={6}>
                  <TextInput label="Alias" value={form.alias} onChange={(event) => updateForm({ alias: event.currentTarget.value, autoAlias: false })} required />
                </Grid.Col>
                <Grid.Col span={12}>
                  <Checkbox label="auto alias" checked={form.autoAlias} onChange={(event) => updateForm({ autoAlias: event.currentTarget.checked })} />
                </Grid.Col>
                <Grid.Col span={12}>
                  <TextInput label="Image" value={form.image} onChange={(event) => updateForm({ image: event.currentTarget.value })} required />
                </Grid.Col>
                {selectedAgent && <Grid.Col span={12}><Alert color="gray">{selectedAgent.agent_url} · {selectedAgent.ssh_host}{selectedAgent.ssh_proxy ? ' · via SSH proxy' : ''}</Alert></Grid.Col>}
                <Grid.Col span={12}>
                  <Textarea label="Extra repos" placeholder="owner/repo，每行一个或用逗号分隔" minRows={3} value={form.extraRepos} onChange={(event) => updateForm({ extraRepos: event.currentTarget.value })} />
                </Grid.Col>
              </Grid>
              <Group justify="flex-end">
                <Button variant="default" onClick={() => setCreateOpen(false)}>Cancel</Button>
                <Button type="submit" loading={submitting}>Create</Button>
              </Group>
            </Stack>
          </form>
        </Modal>

        <Stack className="toast-area" gap="xs">
          {toasts.map((toast) => (
            <Alert key={toast.id} color={toast.tone === 'danger' ? 'red' : toast.tone === 'warning' ? 'yellow' : 'green'} withCloseButton onClose={() => setToasts((items) => items.filter((item) => item.id !== toast.id))}>
              {toast.message}
            </Alert>
          ))}
        </Stack>
      </Box>
    </MantineProvider>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <Grid.Col span={3}>
      <Paper withBorder radius="md" p="sm" className="stat-card">
        <Text size="xs" c="dimmed">{label}</Text>
        <Text fw={700}>{value}</Text>
      </Paper>
    </Grid.Col>
  );
}

function SidePanel({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <Paper withBorder radius="md" className="panel-card">
      <Group justify="space-between" className="panel-heading compact">
        <Title order={2} size="h6">{title}</Title>
        {action}
      </Group>
      <Box p="sm">{children}</Box>
    </Paper>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
