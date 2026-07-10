import '@radix-ui/themes/styles.css';
import './styles.css';

import { Box, Callout, Flex, Text, Theme } from '@radix-ui/themes';
import { useState } from 'react';
import { createRoot } from 'react-dom/client';

import { request } from './api';
import { AgentBar } from './components/AgentBar';
import { CodespaceGrid } from './components/CodespaceGrid';
import { CreateDialog } from './components/CreateDialog';
import { TopBar } from './components/TopBar';
import { useDashboard } from './hooks/useDashboard';
import { useToast } from './hooks/useToast';
import type { CreateForm, InstanceCard, Operation } from './types';
import { existingInstances, instanceAlias, nextInstanceName } from './utils';

const emptyForm: CreateForm = {
  agent: '',
  repo: '',
  provider: 'github',
  template: '',
  instance: 'default',
  image: '',
};

function App() {
  const { toasts, showToast, dismissToast } = useToast();
  const state = useDashboard(showToast);
  const { config, dashboard, operations, tokenStatus } = state;

  const [agentFilter, setAgentFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [createOpen, setCreateOpen] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [form, setForm] = useState<CreateForm>(emptyForm);

  function selectTemplate(templateId: string) {
    if (!config) return;
    const template = config.templates.find((item) => item.id === templateId);
    if (!template) return;
    const agent = template.agent || config.default_agent;
    const used = existingInstances(dashboard.codespaces, operations.values(), agent, template.id);
    setForm({
      agent,
      repo: template.repo,
      provider: template.provider,
      template: template.id,
      instance: nextInstanceName(used),
      image: template.image || config.defaults.image,
    });
    setCreateError(null);
  }

  function openCreate() {
    if (!config) return;
    setCreateError(null);
    if (form.template === '' && config.templates.length > 0) selectTemplate(config.templates[0].id);
    setCreateOpen(true);
  }

  async function submitCreate() {
    if (!config || !form.template) return;
    setSubmitting(true);
    try {
      const payload = {
        repo: form.repo.trim(),
        provider: form.provider,
        template: form.template.trim(),
        instance: form.instance.trim(),
        image: form.image.trim(),
      };
      const used = existingInstances(dashboard.codespaces, operations.values(), form.agent, payload.template);
      if (used.has(payload.instance)) {
        throw new Error(`Instance already exists: ${form.agent}/${payload.template}/${payload.instance}`);
      }
      if (!tokenStatus[form.provider].has_token) {
        throw new Error(`请先保存 ${form.provider === 'gitlab' ? 'GitLab' : 'GitHub'} token`);
      }
      const alias = instanceAlias(form.agent, payload.template, payload.instance);
      const result = await request<{ operation_id: string }>(
        `/api/agents/${encodeURIComponent(form.agent)}/codespaces`,
        { method: 'POST', body: JSON.stringify(payload) },
      );
      setCreateOpen(false);
      const now = Date.now() / 1000;
      const operation: Operation = {
        id: result.operation_id,
        status: 'queued',
        stage: 'queued',
        alias,
        repo: payload.repo,
        provider: payload.provider,
        template: payload.template,
        instance: payload.instance,
        agent_id: form.agent,
        created_at: now,
        updated_at: now,
      };
      state.addOperation(operation);
      showToast(`Create started: ${alias}`);
    } catch (submitError) {
      const message = (submitError as Error).message;
      setCreateError(message);
      showToast(message, 'danger');
    } finally {
      setSubmitting(false);
    }
  }

  async function deleteCodespace(card: InstanceCard, purge: boolean) {
    if (!card.id) return;
    const confirmed = window.confirm(
      purge ? '确认删除容器，并同时删除 workspace 目录？' : '确认只删除容器？workspace 会保留。',
    );
    if (!confirmed) return;
    try {
      const result = await request<{ warning?: string | null }>(
        `/api/agents/${encodeURIComponent(card.agent_id)}/codespaces/${encodeURIComponent(card.id)}` +
          `?repo=${encodeURIComponent(card.repo)}&provider=${encodeURIComponent(card.provider)}` +
          `${purge ? '&purge=true' : ''}`,
        { method: 'DELETE' },
      );
      state.setError(result.warning || null);
      showToast(result.warning || 'Codespace deleted', result.warning ? 'warning' : 'success');
      state.dropOperations(
        (op) => op.agent_id === card.agent_id && op.template === card.template && op.instance === card.instance,
      );
      await state.refresh();
    } catch (deleteError) {
      state.setError((deleteError as Error).message);
    }
  }

  function dismissOperation(card: InstanceCard) {
    state.dropOperations(
      (op) => op.agent_id === card.agent_id && op.template === card.template && op.instance === card.instance,
    );
  }

  const providerHasToken = tokenStatus[form.provider].has_token;

  return (
    <Theme appearance="light" accentColor="indigo" radius="medium">
      <Flex direction="column" minHeight="100vh" className="app-shell">
        <TopBar
          refreshing={state.refreshing}
          tokenStatus={tokenStatus}
          onNew={openCreate}
          onRefresh={() => void state.refresh()}
          onSaveToken={async (provider, token) => {
            const ok = await state.saveToken(provider, token);
            if (ok) showToast(`${provider === 'gitlab' ? 'GitLab' : 'GitHub'} token 已保存`);
            return ok;
          }}
        />
        <AgentBar
          agents={dashboard.agents}
          agentFilter={agentFilter}
          query={query}
          lastUpdated={state.lastUpdated}
          onToggleAgent={(id) => setAgentFilter((current) => (current === id ? 'all' : id))}
          onQueryChange={setQuery}
        />
        {state.error && (
          <Box px="4" pt="2">
            <Callout.Root color="amber" size="1">
              <Callout.Text>{state.error}</Callout.Text>
            </Callout.Root>
          </Box>
        )}
        <Box flexGrow="1">
          <CodespaceGrid
            codespaces={dashboard.codespaces}
            operations={operations}
            agentFilter={agentFilter}
            query={query}
            onConnectCopied={(message, ok) => showToast(message, ok ? 'success' : 'danger')}
            onDelete={(card, purge) => void deleteCodespace(card, purge)}
            onDismissOperation={dismissOperation}
          />
        </Box>
      </Flex>

      <CreateDialog
        open={createOpen}
        config={config}
        form={form}
        error={createError}
        submitting={submitting}
        providerHasToken={providerHasToken}
        onOpenChange={setCreateOpen}
        onSelectTemplate={selectTemplate}
        onInstanceChange={(value) => setForm((current) => ({ ...current, instance: value }))}
        onSubmit={() => void submitCreate()}
      />

      <Flex direction="column" gap="2" className="toast-area">
        {toasts.map((toast) => (
          <Callout.Root
            key={toast.id}
            color={toast.tone === 'danger' ? 'red' : toast.tone === 'warning' ? 'amber' : 'green'}
            onClick={() => dismissToast(toast.id)}
            className="toast"
          >
            <Callout.Text>
              <Text size="2">{toast.message}</Text>
            </Callout.Text>
          </Callout.Root>
        ))}
      </Flex>
    </Theme>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
