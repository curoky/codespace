import '@radix-ui/themes/styles.css';
import './styles.css';

import { Box, Callout, Flex, Text, Theme } from '@radix-ui/themes';
import { useState } from 'react';
import { createRoot } from 'react-dom/client';

import { request } from './api';
import { AgentBar } from './components/AgentBar';
import { CreateDialog } from './components/CreateDialog';
import { ProjectGrid } from './components/ProjectGrid';
import { TopBar } from './components/TopBar';
import { useDashboard } from './hooks/useDashboard';
import { useToast } from './hooks/useToast';
import type { InstanceCard, Operation, Project } from './types';
import { existingInstances, instanceAlias, nextInstanceName } from './utils';

function App() {
  const { toasts, showToast, dismissToast } = useToast();
  const state = useDashboard(showToast);
  const { config, dashboard, operations, tokenStatus } = state;

  const [agentFilter, setAgentFilter] = useState('all');
  const [query, setQuery] = useState('');
  const [dialogProject, setDialogProject] = useState<Project | null>(null);
  const [dialogInstance, setDialogInstance] = useState('');
  const [submitting, setSubmitting] = useState(false);

  /** Shared create path used by both the empty-state one-click and the dialog. */
  async function createInstance(project: Project, instanceName: string): Promise<boolean> {
    if (!config) return false;
    const template = config.templates.find((item) => item.id === project.id);
    if (!template) return false;
    const instance = instanceName.trim();
    if (!instance) return false;

    const used = existingInstances(dashboard.codespaces, operations.values(), project.agent, template.id);
    if (used.has(instance)) {
      showToast(`Instance already exists: ${project.agent}/${template.id}/${instance}`, 'danger');
      return false;
    }
    if (!tokenStatus[template.provider].has_token) {
      showToast(`请先保存 ${template.provider === 'gitlab' ? 'GitLab' : 'GitHub'} token`, 'danger');
      return false;
    }

    const payload = {
      repo: template.repo,
      provider: template.provider,
      template: template.id,
      instance,
      image: template.image || config.defaults.image,
    };
    const alias = instanceAlias(project.agent, template.id, instance);
    try {
      const result = await request<{ operation_id: string }>(
        `/api/agents/${encodeURIComponent(project.agent)}/codespaces`,
        { method: 'POST', body: JSON.stringify(payload) },
      );
      const now = Date.now() / 1000;
      const operation: Operation = {
        id: result.operation_id,
        status: 'queued',
        stage: 'queued',
        alias,
        repo: payload.repo,
        provider: payload.provider,
        template: payload.template,
        instance,
        agent_id: project.agent,
        created_at: now,
        updated_at: now,
      };
      state.addOperation(operation);
      showToast(`Create started: ${alias}`);
      return true;
    } catch (createError) {
      showToast((createError as Error).message, 'danger');
      return false;
    }
  }

  function suggestName(project: Project): string {
    const used = existingInstances(dashboard.codespaces, operations.values(), project.agent, project.id);
    return nextInstanceName(used);
  }

  function createDefault(project: Project) {
    void createInstance(project, suggestName(project));
  }

  function openNewInstance(project: Project) {
    setDialogInstance(suggestName(project));
    setDialogProject(project);
  }

  async function submitDialog() {
    if (!dialogProject) return;
    setSubmitting(true);
    const ok = await createInstance(dialogProject, dialogInstance);
    setSubmitting(false);
    if (ok) setDialogProject(null);
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

  const dialogProviderHasToken = dialogProject ? tokenStatus[dialogProject.provider].has_token : true;

  return (
    <Theme appearance="light" accentColor="indigo" radius="medium">
      <Flex direction="column" minHeight="100vh" className="app-shell">
        <TopBar
          refreshing={state.refreshing}
          tokenStatus={tokenStatus}
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
          onToggleAgent={(id) => setAgentFilter((current) => (current === id ? 'all' : id))}
          onQueryChange={setQuery}
        />
        {state.error && (
          <Box px="4" pt="3">
            <Box className="page-inner">
              <Callout.Root color="amber" size="1">
                <Callout.Text>{state.error}</Callout.Text>
              </Callout.Root>
            </Box>
          </Box>
        )}
        <Box flexGrow="1">
          <ProjectGrid
            config={config}
            codespaces={dashboard.codespaces}
            operations={operations}
            agentFilter={agentFilter}
            query={query}
            onCreateDefault={createDefault}
            onNewInstance={openNewInstance}
            onConnectCopied={(message, ok) => showToast(message, ok ? 'success' : 'danger')}
            onDelete={(card, purge) => void deleteCodespace(card, purge)}
            onDismissOperation={dismissOperation}
          />
        </Box>
      </Flex>

      <CreateDialog
        project={dialogProject}
        instance={dialogInstance}
        submitting={submitting}
        providerHasToken={dialogProviderHasToken}
        onOpenChange={(open) => {
          if (!open) setDialogProject(null);
        }}
        onInstanceChange={setDialogInstance}
        onSubmit={() => void submitDialog()}
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
