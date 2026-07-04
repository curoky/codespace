import '@mantine/core/styles.css';
import './styles.css';

import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Box,
  Button,
  Checkbox,
  Code,
  Container,
  Flex,
  Grid,
  Group,
  MantineProvider,
  Modal,
  NumberFormatter,
  Paper,
  Progress,
  ScrollArea,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { IconChevronDown, IconChevronRight, IconPlus, IconRefresh } from '@tabler/icons-react';
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';

type AgentStatus = 'online' | 'offline';
type OperationStatus = 'queued' | 'running' | 'succeeded' | 'failed';

type ConfigSummary = {
  default_agent: string;
  defaults: {
    image: string;
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
    image?: string | null;
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

type Operation = {
  id: string;
  agent_id: string;
  alias: string;
  repo: string;
  template: string;
  instance: string;
  status: OperationStatus;
  stage: string;
  error?: string | null;
  created_at: number;
  _polling?: boolean;
};

type InstanceRow = {
  key: string;
  agent_id: string;
  repo: string;
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

type FilterState = {
  agent: string;
  status: string;
  sort: 'agent' | 'repo' | 'template' | 'instance' | 'alias' | 'status';
};

type CreateForm = {
  agent: string;
  repo: string;
  template: string;
  instance: string;
  image: string;
};

type Toast = {
  id: number;
  message: string;
  tone: 'success' | 'warning' | 'danger';
};

const emptyDashboard: Dashboard = { agents: [], codespaces: [], operations: [] };
const defaultFilter: FilterState = { agent: 'all', status: 'all', sort: 'agent' };

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

function instanceAlias(agent: string, template: string, instance: string): string {
  return agent && template && instance ? `${agent}-${template}-${instance}` : '';
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

function instanceKey(agent: string, template: string, instance: string): string {
  return `${agent}:${template}:${instance}`;
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
  const [expandedTemplates, setExpandedTemplates] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<FilterState>(defaultFilter);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [createOpen, setCreateOpen] = useState(false);
  const [createTemplateId, setCreateTemplateId] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [form, setForm] = useState<CreateForm>({
    agent: '',
    repo: '',
    template: 'default',
    instance: 'default',
    image: '',
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
    return dashboard.codespaces
      .filter((cs) => {
        const status = normalizeStatus(cs.status);
        return (
          (filter.agent === 'all' || cs.agent_id === filter.agent) &&
          (filter.status === 'all' || status === filter.status || (filter.status === 'unknown' && !cs.status))
        );
      })
      .sort((left, right) => {
        const leftValue = filter.sort === 'agent' ? left.agent_id : left[filter.sort];
        const rightValue = filter.sort === 'agent' ? right.agent_id : right[filter.sort];
        return String(leftValue || '').localeCompare(String(rightValue || ''));
      });
  }, [dashboard.codespaces, filter]);

  const instanceRows = useMemo<InstanceRow[]>(() => {
    const rows = new Map<string, InstanceRow>();
    for (const cs of filteredCodespaces) {
      rows.set(instanceKey(cs.agent_id, cs.template, cs.instance), {
        key: instanceKey(cs.agent_id, cs.template, cs.instance),
        agent_id: cs.agent_id,
        repo: cs.repo,
        template: cs.template,
        instance: cs.instance,
        alias: cs.alias,
        id: cs.id,
        ssh_host: cs.ssh_host,
        port: cs.port,
        status: cs.status,
        raw_ssh_command: cs.raw_ssh_command,
        trae_url: cs.trae_url,
        kind: 'codespace',
      });
    }
    for (const op of operations.values()) {
      const key = instanceKey(op.agent_id, op.template, op.instance);
      if (rows.has(key) && op.status === 'succeeded') continue;
      const status = normalizeStatus(op.status);
      if (filter.agent !== 'all' && op.agent_id !== filter.agent) continue;
      if (filter.status !== 'all' && status !== filter.status) continue;
      rows.set(key, {
        key,
        agent_id: op.agent_id,
        repo: op.repo,
        template: op.template,
        instance: op.instance,
        alias: op.alias,
        id: op.id,
        status: op.status,
        stage: op.stage,
        error: op.error,
        kind: 'operation',
      });
    }
    return [...rows.values()].sort((left, right) => {
      const value = (row: InstanceRow) => {
        if (filter.sort === 'agent') return row.agent_id;
        return row[filter.sort] || '';
      };
      return String(value(left)).localeCompare(String(value(right)));
    });
  }, [filteredCodespaces, operations, filter]);

  const templateRows = useMemo(() => {
    if (!config) return [];
    const configured = config.templates.map((template) => ({
      key: `${template.agent || config.default_agent}:${template.id}`,
      id: template.id,
      repo: template.repo,
      agent: template.agent || config.default_agent,
      description: template.description,
      image: template.image || config.defaults.image,
    }));
    const known = new Set(configured.map((row) => row.key));
    const adHoc = dashboard.codespaces
      .filter((cs) => !known.has(`${cs.agent_id}:${cs.template}`))
      .map((cs) => ({
        key: `${cs.agent_id}:${cs.template}`,
        id: cs.template,
        repo: cs.repo,
        agent: cs.agent_id,
        description: null,
        image: config.defaults.image,
      }));
    const rows = [...configured, ...adHoc.filter((row, index, list) => list.findIndex((item) => item.key === row.key) === index)];
    return rows
      .map((row) => ({
        ...row,
        instances: instanceRows.filter((instance) => instance.agent_id === row.agent && instance.template === row.id),
      }))
      .filter((row) => {
        if (filter.agent !== 'all' && row.agent !== filter.agent) return false;
        return row.instances.length > 0 || config.templates.some((template) => template.id === row.id);
      })
      .sort((left, right) => {
        const sortValue = (row: { agent: string; repo: string; id: string }) => {
          if (filter.sort === 'agent') return row.agent;
          if (filter.sort === 'repo') return row.repo;
          return row.id;
        };
        return String(sortValue(left)).localeCompare(String(sortValue(right)));
      });
  }, [config, dashboard.codespaces, instanceRows, filter]);

  function toggleTemplate(key: string) {
    setExpandedTemplates((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function updateForm(patch: Partial<CreateForm>) {
    setForm((current) => ({ ...current, ...patch }));
  }

  function openCreate(templateId?: string) {
    if (!config) return;
    const template = config.templates.find((item) => item.id === templateId);
    const agent = template?.agent || (filter.agent !== 'all' ? filter.agent : config.default_agent);
    const repo = template?.repo || '';
    const nextForm: CreateForm = {
      agent,
      repo,
      template: template?.id || 'default',
      instance: 'default',
      image: template?.image || config.defaults.image,
    };
    setForm(nextForm);
    setCreateTemplateId(template?.id || null);
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
        template: form.template.trim(),
        instance: form.instance.trim(),
        image: form.image.trim(),
      };
      const alias = instanceAlias(form.agent, payload.template, payload.instance);
      const result = await request<{ operation_id: string }>(
        `/api/agents/${encodeURIComponent(form.agent)}/codespaces`,
        { method: 'POST', body: JSON.stringify(payload) },
      );
      setCreateOpen(false);
      const operation: Operation = {
        id: result.operation_id,
        status: 'queued',
        stage: 'queued',
        alias,
        ...payload,
        agent_id: form.agent,
        created_at: Date.now() / 1000,
      };
      setOperations((current) => new Map(current).set(result.operation_id, operation));
      showToast(`Create operation started: ${alias}`);
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

  const selectedAgent = config?.agents.find((agent) => agent.id === form.agent);
  const selectedTemplate = createTemplateId
    ? config?.templates.find((template) => template.id === createTemplateId)
    : null;

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
            <Paper withBorder radius="md" className="runtime-strip">
              <Group gap="sm" justify="space-between" align="center">
                <Group gap="xs" className="runtime-strip-section">
                  <Badge variant="light" color={config?.github.has_token ? 'green' : 'yellow'}>
                    {config?.github.has_token ? 'Token ready' : 'Token missing'}
                  </Badge>
                  <Text size="xs" c="dimmed">{config?.github.has_token ? config.github.token_env : `set ${config?.github.token_env || 'GITHUB_TOKEN'}`}</Text>
                  <Text size="xs" c="dimmed">Updated {formatTime(lastUpdated)}</Text>
                  <Checkbox size="xs" label="auto refresh" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.currentTarget.checked)} />
                </Group>
                <Group gap={6} className="agent-chips">
                  {dashboard.agents.length ? dashboard.agents.map((agent) => (
                    <Button
                      key={agent.id}
                      size="compact-xs"
                      variant={filter.agent === agent.id ? 'filled' : 'light'}
                      color={statusColor(agent.status)}
                      onClick={() => setFilter((current) => ({ ...current, agent: current.agent === agent.id ? 'all' : agent.id }))}
                    >
                      {agent.id}{agent.ssh_proxy ? ' · proxy' : ''}
                    </Button>
                  )) : <Text c="dimmed" size="xs">暂无 agent 信息</Text>}
                </Group>
              </Group>
              {dashboard.agents.some((agent) => agent.error) && (
                <Stack gap={4} mt="xs">
                  {dashboard.agents.filter((agent) => agent.error).map((agent) => (
                    <Alert key={agent.id} color="red" py={4}>{agent.id}: {agent.error}</Alert>
                  ))}
                </Stack>
              )}
            </Paper>
            {error && <Alert color="yellow">{error}</Alert>}
            <Paper withBorder radius="md" className="panel-card">
              <Group justify="space-between" className="panel-heading">
                <Title order={2} size="h5">Templates</Title>
                <Badge variant="light"><NumberFormatter value={templateRows.length} /></Badge>
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
                <Select
                  size="xs"
                  data={[
                    { value: 'agent', label: 'Agent' },
                    { value: 'repo', label: 'Repository' },
                    { value: 'template', label: 'Template' },
                    { value: 'instance', label: 'Instance' },
                    { value: 'alias', label: 'Alias' },
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
                      <Table.Th>Template</Table.Th>
                      <Table.Th>Repo</Table.Th>
                      <Table.Th>Status</Table.Th>
                      <Table.Th>Runtime</Table.Th>
                      <Table.Th ta="right">Actions</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {templateRows.map((template) => (
                      <React.Fragment key={template.key}>
                        <Table.Tr className="template-row">
                          <Table.Td>
                            <Group gap="xs" wrap="nowrap">
                              <ActionIcon size="sm" variant="subtle" onClick={() => toggleTemplate(template.key)} disabled={template.instances.length === 0}>
                                {expandedTemplates.has(template.key) ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
                              </ActionIcon>
                              <Box>
                                <Text fw={700}>{template.id}</Text>
                                {template.description && <Text size="xs" c="dimmed">{template.description}</Text>}
                              </Box>
                            </Group>
                          </Table.Td>
                          <Table.Td><Text fw={600}>{template.repo}</Text></Table.Td>
                          <Table.Td><Text c="dimmed" size="xs">template</Text></Table.Td>
                          <Table.Td><Badge variant="light"><NumberFormatter value={template.instances.length} /></Badge></Table.Td>
                          <Table.Td>
                            <Group justify="flex-end" gap="xs" wrap="nowrap">
                              <Button size="compact-xs" leftSection={<IconPlus size={14} />} onClick={() => openCreate(template.id)}>New instance</Button>
                            </Group>
                          </Table.Td>
                        </Table.Tr>
                        {expandedTemplates.has(template.key) && template.instances.map((instance) => {
                          const isCodespace = isCodespaceRow(instance);
                          return (
                            <Table.Tr key={instance.key} className={`instance-row ${instance.kind === 'operation' ? 'operation-instance-row' : ''}`}>
                              <Table.Td colSpan={5}>
                                <Paper withBorder radius="md" className="instance-card">
                                  <Group justify="space-between" align="flex-start" gap="md" wrap="nowrap">
                                    <Box className="instance-main">
                                      <Group gap="xs" wrap="nowrap">
                                        <Badge size="sm" variant="light" color="blue">instance</Badge>
                                        <Text fw={700}>{instance.instance}</Text>
                                        <Badge color={statusColor(instance.status)} variant="light">{instance.status || 'unknown'}</Badge>
                                      </Group>
                                      <Group gap="xs" mt={6} className="instance-meta">
                                        <Anchor component="button" type="button" size="xs" onClick={() => setFilter((current) => ({ ...current, agent: instance.agent_id }))}>
                                          {instance.agent_id}
                                        </Anchor>
                                        {instance.alias && <Code>{instance.alias}</Code>}
                                        <Text size="xs" c="dimmed">{instance.kind === 'operation' ? instance.stage : instance.id}</Text>
                                      </Group>
                                      {instance.kind === 'operation' && <Progress mt="xs" size="xs" value={operationProgress(instance.status as OperationStatus)} color={statusColor(instance.status)} />}
                                      {instance.error && <Text size="xs" c="red" mt={4}>{instance.error}</Text>}
                                      <Text size="xs" c="dimmed" mt={4} className="instance-command">{instance.raw_ssh_command || instance.id}</Text>
                                    </Box>
                                    <Group gap="xs" wrap="nowrap" className="instance-actions">
                                      {isCodespace && <Button size="compact-xs" component="a" href={instance.trae_url}>Trae IDE</Button>}
                                      {isCodespace && <Button size="compact-xs" variant="default" color="red" onClick={() => void deleteCodespace(instance, false)}>Delete</Button>}
                                      {isCodespace && <Button size="compact-xs" color="red" onClick={() => void deleteCodespace(instance, true)}>Purge</Button>}
                                    </Group>
                                  </Group>
                                </Paper>
                              </Table.Td>
                            </Table.Tr>
                          );
                        })}
                      </React.Fragment>
                    ))}
                  </Table.Tbody>
                </Table>
              </ScrollArea>
              {templateRows.length === 0 && <Text c="dimmed" p="md">暂无 template</Text>}
            </Paper>
            {operations.size > 0 && <Group justify="flex-end"><Button size="compact-xs" variant="default" onClick={() => void clearOperations()}>Clear completed operations</Button></Group>}
          </Stack>
        </Container>

        <Modal
          opened={createOpen}
          onClose={() => setCreateOpen(false)}
          title={selectedTemplate ? `New instance · ${selectedTemplate.id}` : 'Create Codespace'}
          size={selectedTemplate ? 'md' : 'lg'}
          centered
        >
          <form onSubmit={submitCreate}>
            <Stack>
              {createError && <Alert color="red">{createError}</Alert>}
              {config && !config.github.has_token && <Alert color="yellow">创建 codespace 需要 GitHub token。请在启动 Web GUI 前设置 {config.github.token_env}。</Alert>}
              {selectedTemplate ? (
                <Stack gap="sm">
                  <Paper withBorder radius="md" p="sm" className="create-summary">
                    <Group justify="space-between" gap="xs">
                      <Box>
                        <Text fw={700}>{selectedTemplate.id}</Text>
                        <Text size="xs" c="dimmed">{selectedTemplate.description || selectedTemplate.repo}</Text>
                      </Box>
                      <Badge variant="light">{form.agent}</Badge>
                    </Group>
                    <Group gap="xs" mt="xs">
                      <Code>{form.repo}</Code>
                      <Text size="xs" c="dimmed">{form.image}</Text>
                    </Group>
                  </Paper>
                  <TextInput
                    label="Instance name"
                    value={form.instance}
                    onChange={(event) => updateForm({ instance: event.currentTarget.value })}
                    autoFocus
                    required
                  />
                  <Alert color="gray">Local SSH alias: <Code>{instanceAlias(form.agent, form.template, form.instance) || '-'}</Code></Alert>
                </Stack>
              ) : (
                <Grid>
                  <Grid.Col span={6}>
                    <Select label="Agent" data={config?.agents.map((agent) => ({ value: agent.id, label: agent.id })) || []} value={form.agent} onChange={(value) => updateForm({ agent: value || '' })} required />
                  </Grid.Col>
                  <Grid.Col span={6}>
                    <TextInput label="Repo" placeholder="owner/name" value={form.repo} onChange={(event) => updateForm({ repo: event.currentTarget.value })} required />
                  </Grid.Col>
                  <Grid.Col span={6}>
                    <TextInput label="Template" value={form.template} onChange={(event) => updateForm({ template: event.currentTarget.value })} required />
                  </Grid.Col>
                  <Grid.Col span={6}>
                    <TextInput label="Instance name" value={form.instance} onChange={(event) => updateForm({ instance: event.currentTarget.value })} required />
                  </Grid.Col>
                  <Grid.Col span={12}>
                    <Alert color="gray">Local SSH alias: <Code>{instanceAlias(form.agent, form.template, form.instance) || '-'}</Code></Alert>
                  </Grid.Col>
                  <Grid.Col span={12}>
                    <TextInput label="Image" value={form.image} onChange={(event) => updateForm({ image: event.currentTarget.value })} required />
                  </Grid.Col>
                  {selectedAgent && <Grid.Col span={12}><Alert color="gray">{selectedAgent.agent_url} · {selectedAgent.ssh_host}{selectedAgent.ssh_proxy ? ' · via SSH proxy' : ''}</Alert></Grid.Col>}
                </Grid>
              )}
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

function isCodespaceRow(row: InstanceRow): row is InstanceRow & Codespace {
  return row.kind === 'codespace';
}

createRoot(document.getElementById('root')!).render(<App />);
