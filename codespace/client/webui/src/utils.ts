import type { Codespace, InstanceCard, Operation } from './types';

/** Radix Themes accent colors used across the UI. */
export type AccentColor = 'green' | 'red' | 'amber' | 'orange' | 'gray';

export function instanceAlias(agent: string, template: string, instance: string): string {
  return agent && template && instance ? `${agent}-${template}-${instance}` : '';
}

export function instanceKey(agent: string, template: string, instance: string): string {
  return `${agent}:${template}:${instance}`;
}

export function normalizeStatus(status?: string | null): string {
  return String(status || 'unknown').toLowerCase();
}

export function isBusyOperation(op: Operation): boolean {
  return op.status === 'queued' || op.status === 'running';
}

export function isCodespaceCard(card: InstanceCard): card is InstanceCard & Codespace {
  return card.kind === 'codespace';
}

export function operationProgress(status?: string | null): number {
  const normalized = normalizeStatus(status);
  if (normalized === 'queued') return 12;
  if (normalized === 'running') return 58;
  return normalized === 'succeeded' || normalized === 'failed' ? 100 : 0;
}

/** Map a codespace/agent/operation status to a Radix accent color. */
export function statusColor(status?: string | null): AccentColor {
  const normalized = normalizeStatus(status);
  if (['online', 'running', 'succeeded'].includes(normalized)) return 'green';
  if (['offline', 'failed'].includes(normalized)) return 'red';
  if (normalized === 'queued') return 'amber';
  return 'gray';
}

export function providerColor(provider: string): AccentColor {
  return provider === 'gitlab' ? 'orange' : 'gray';
}

export function formatTime(timestamp: number | null): string {
  return timestamp ? new Date(timestamp).toLocaleTimeString() : '尚未刷新';
}

/** The command a user runs to connect: prefer the local SSH alias. */
export function connectCommand(card: Pick<InstanceCard, 'alias' | 'raw_ssh_command'>): string {
  if (card.alias) return `ssh ${card.alias}`;
  return card.raw_ssh_command || '';
}

export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** Instances already taken by a codespace or in-flight operation. */
export function existingInstances(
  codespaces: Codespace[],
  operations: Iterable<Operation>,
  agent: string,
  template: string,
): Set<string> {
  const used = new Set<string>();
  for (const cs of codespaces) {
    if (cs.agent_id === agent && cs.template === template) used.add(cs.instance);
  }
  for (const op of operations) {
    if (op.agent_id === agent && op.template === template && isBusyOperation(op)) {
      used.add(op.instance);
    }
  }
  return used;
}

/** Suggest the next free instance name, e.g. default -> default-2 -> default-3. */
export function nextInstanceName(used: Set<string>): string {
  if (!used.has('default')) return 'default';
  for (let index = 2; ; index += 1) {
    const candidate = `default-${index}`;
    if (!used.has(candidate)) return candidate;
  }
}
