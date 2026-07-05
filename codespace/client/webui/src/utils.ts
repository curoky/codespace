import type { Codespace, InstanceRow, Operation, OperationStatus } from './types';

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

const envNameRe = /^[A-Za-z_][A-Za-z0-9_]*$/;
const reservedEnvNames = new Set(['SSHD_PORT']);

export function parseEnvText(text: string): Record<string, string> {
  const env: Record<string, string> = {};
  const lines = text.split(/\r?\n/);
  lines.forEach((rawLine, index) => {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) return;
    const separator = line.indexOf('=');
    if (separator <= 0) throw new Error(`环境变量第 ${index + 1} 行必须是 KEY=VALUE 格式`);
    const key = line.slice(0, separator).trim();
    const value = line.slice(separator + 1);
    if (!envNameRe.test(key)) throw new Error(`环境变量名无效: ${key}`);
    if (reservedEnvNames.has(key)) throw new Error(`${key} 是系统保留环境变量，不能覆盖`);
    if (value.includes('\0')) throw new Error(`${key} 的值不能包含 NUL 字符`);
    env[key] = value;
  });
  return env;
}
