import type { Codespace, InstanceRow, Operation, OperationStatus, StatusFilter } from './types';

export const STATUS_FILTER_OPTIONS: Array<{ value: StatusFilter; label: string }> = [
  { value: 'all', label: 'All status' },
  { value: 'running', label: 'Running' },
  { value: 'stopped', label: 'Stopped' },
  { value: 'queued', label: 'Queued' },
  { value: 'failed', label: 'Failed' },
  { value: 'unknown', label: 'Unknown' },
];

export function isStatusFilter(value: string): value is StatusFilter {
  return STATUS_FILTER_OPTIONS.some((option) => option.value === value);
}

export function instanceAlias(agent: string, template: string, instance: string): string {
  return agent && template && instance ? `${agent}-${template}-${instance}` : '';
}

export function normalizeStatus(status?: string | null): string {
  return String(status || 'unknown').toLowerCase();
}

export function isBusyOperation(op: Operation): boolean {
  return op.status === 'queued' || op.status === 'running';
}

export function operationProgress(status: OperationStatus): number {
  if (status === 'queued') return 12;
  if (status === 'running') return 58;
  return status === 'succeeded' || status === 'failed' ? 100 : 0;
}

export function instanceKey(agent: string, template: string, instance: string): string {
  return `${agent}:${template}:${instance}`;
}

export function statusColor(status?: string | null): string {
  const normalized = normalizeStatus(status);
  if (['online', 'running', 'succeeded'].includes(normalized)) return 'green';
  if (['offline', 'failed'].includes(normalized)) return 'red';
  if (normalized === 'queued') return 'yellow';
  return 'gray';
}

export function formatTime(timestamp: number | null): string {
  return timestamp ? new Date(timestamp).toLocaleTimeString() : '尚未刷新';
}

export function isCodespaceRow(row: InstanceRow): row is InstanceRow & Codespace {
  return row.kind === 'codespace';
}
