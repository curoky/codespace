import { Box, Grid, Text } from '@radix-ui/themes';
import { useMemo } from 'react';

import type { Codespace, InstanceCard, Operation } from '../types';
import { instanceKey, normalizeStatus } from '../utils';
import { CodespaceCard } from './CodespaceCard';

type Props = {
  codespaces: Codespace[];
  operations: Map<string, Operation>;
  agentFilter: string;
  query: string;
  onConnectCopied: (message: string, ok: boolean) => void;
  onDelete: (card: InstanceCard, purge: boolean) => void;
  onDismissOperation: (card: InstanceCard) => void;
};

function matchesQuery(card: InstanceCard, query: string): boolean {
  if (!query) return true;
  const haystack = `${card.repo} ${card.instance} ${card.template} ${card.alias || ''}`.toLowerCase();
  return haystack.includes(query.toLowerCase());
}

/** Merge ready codespaces and in-flight operations into one card list. */
function buildCards(codespaces: Codespace[], operations: Map<string, Operation>): InstanceCard[] {
  const cards = new Map<string, InstanceCard>();
  for (const cs of codespaces) {
    cards.set(instanceKey(cs.agent_id, cs.template, cs.instance), {
      key: instanceKey(cs.agent_id, cs.template, cs.instance),
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

export function CodespaceGrid({
  codespaces,
  operations,
  agentFilter,
  query,
  onConnectCopied,
  onDelete,
  onDismissOperation,
}: Props) {
  const cards = useMemo(() => {
    return buildCards(codespaces, operations)
      .filter((card) => agentFilter === 'all' || card.agent_id === agentFilter)
      .filter((card) => matchesQuery(card, query))
      .sort((left, right) => {
        // In-flight operations first, then by agent/template/instance.
        const rank = (card: InstanceCard) => (card.kind === 'operation' ? 0 : 1);
        if (rank(left) !== rank(right)) return rank(left) - rank(right);
        return left.key.localeCompare(right.key);
      });
  }, [codespaces, operations, agentFilter, query]);

  if (cards.length === 0) {
    return (
      <Box p="6">
        <Text color="gray" align="center" as="div">
          {normalizeStatus(agentFilter) === 'all' && !query
            ? '暂无 codespace。点击右上角 New codespace 创建。'
            : '没有匹配的 codespace。'}
        </Text>
      </Box>
    );
  }

  return (
    <Grid columns={{ initial: '1', xs: '2', md: '3', lg: '4' }} gap="3" p="4">
      {cards.map((card) => (
        <CodespaceCard
          key={card.key}
          card={card}
          onConnectCopied={onConnectCopied}
          onDelete={onDelete}
          onDismissOperation={onDismissOperation}
        />
      ))}
    </Grid>
  );
}
