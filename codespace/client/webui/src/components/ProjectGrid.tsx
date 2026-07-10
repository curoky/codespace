import { Box, Flex, Text } from '@radix-ui/themes';
import { useMemo } from 'react';

import type { Codespace, ConfigSummary, InstanceCard, Operation, Project } from '../types';
import { instanceKey, normalizeStatus } from '../utils';
import { ProjectCard } from './ProjectCard';

type Props = {
  config: ConfigSummary | null;
  codespaces: Codespace[];
  operations: Map<string, Operation>;
  agentFilter: string;
  query: string;
  onCreateDefault: (project: Project) => void;
  onNewInstance: (project: Project) => void;
  onConnectCopied: (message: string, ok: boolean) => void;
  onDelete: (card: InstanceCard, purge: boolean) => void;
  onDismissOperation: (card: InstanceCard) => void;
};

const UNKNOWN_ID = '__unknown__';

/** Merge ready codespaces + in-flight operations into cards keyed by identity. */
function buildInstanceCards(codespaces: Codespace[], operations: Map<string, Operation>): InstanceCard[] {
  const cards = new Map<string, InstanceCard>();
  for (const cs of codespaces) {
    const key = instanceKey(cs.agent_id, cs.template, cs.instance);
    cards.set(key, {
      key,
      agent_id: cs.agent_id,
      repo: cs.repo,
      provider: cs.provider,
      template: cs.template,
      instance: cs.instance,
      alias: cs.alias,
      id: cs.id,
      status: cs.status,
      raw_ssh_command: cs.raw_ssh_command,
      trae_url: cs.trae_url,
      kind: 'codespace',
    });
  }
  for (const op of operations.values()) {
    if (op.status === 'succeeded') continue;
    const key = instanceKey(op.agent_id, op.template, op.instance);
    if (cards.has(key)) continue;
    cards.set(key, {
      key,
      agent_id: op.agent_id,
      repo: op.repo,
      provider: op.provider,
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
  return [...cards.values()];
}

/** Project-first grouping: config templates are projects; instances hang below. */
function buildProjects(config: ConfigSummary | null, cards: InstanceCard[]): Project[] {
  const projects = new Map<string, Project>();
  for (const template of config?.templates ?? []) {
    projects.set(template.id, {
      id: template.id,
      description: template.description,
      agent: template.agent || config?.default_agent || '',
      provider: template.provider,
      repo: template.repo,
      known: true,
      instances: [],
    });
  }
  for (const card of cards) {
    const project = projects.get(card.template);
    if (project) {
      project.instances.push(card);
      continue;
    }
    // Codespace whose template is no longer in config: collect under one group.
    let unknown = projects.get(UNKNOWN_ID);
    if (!unknown) {
      unknown = {
        id: '未归类环境',
        description: 'template 不在当前配置中',
        agent: card.agent_id,
        provider: card.provider,
        repo: card.repo,
        known: false,
        instances: [],
      };
      projects.set(UNKNOWN_ID, unknown);
    }
    unknown.instances.push(card);
  }
  for (const project of projects.values()) {
    project.instances.sort((left, right) => {
      const rank = (card: InstanceCard) => (card.kind === 'operation' ? 0 : 1);
      if (rank(left) !== rank(right)) return rank(left) - rank(right);
      return left.instance.localeCompare(right.instance);
    });
  }
  return [...projects.values()];
}

function matchesProject(project: Project, query: string): boolean {
  if (!query) return true;
  const lower = query.toLowerCase();
  if (`${project.id} ${project.repo}`.toLowerCase().includes(lower)) return true;
  return project.instances.some((card) =>
    `${card.instance} ${card.alias || ''}`.toLowerCase().includes(lower),
  );
}

export function ProjectGrid({
  config,
  codespaces,
  operations,
  agentFilter,
  query,
  onCreateDefault,
  onNewInstance,
  onConnectCopied,
  onDelete,
  onDismissOperation,
}: Props) {
  const projects = useMemo(() => {
    const cards = buildInstanceCards(codespaces, operations);
    return buildProjects(config, cards)
      .filter((project) => agentFilter === 'all' || project.agent === agentFilter)
      .filter((project) => matchesProject(project, query));
  }, [config, codespaces, operations, agentFilter, query]);

  if (projects.length === 0) {
    return (
      <Box p="6">
        <Text color="gray" align="center" as="div">
          {normalizeStatus(agentFilter) === 'all' && !query
            ? '暂无项目。请在 config.yaml 的 templates 中添加项目。'
            : '没有匹配的项目。'}
        </Text>
      </Box>
    );
  }

  return (
    <Flex direction="column" gap="3" p="4">
      {projects.map((project) => (
        <ProjectCard
          key={project.id}
          project={project}
          onCreateDefault={onCreateDefault}
          onNewInstance={onNewInstance}
          onConnectCopied={onConnectCopied}
          onDelete={onDelete}
          onDismissOperation={onDismissOperation}
        />
      ))}
    </Flex>
  );
}
