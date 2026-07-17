import { useCallback, useEffect, useRef, useState } from 'react';

import { openOperationStream, request } from '../api';
import type {
  ConfigSummary,
  Dashboard,
  GitProvider,
  Operation,
  TokenStatusResponse,
} from '../types';
import type { ShowToast } from './useToast';

const emptyDashboard: Dashboard = { agents: [], codespaces: [], operations: [] };
const emptyTokenStatus: TokenStatusResponse = {
  github: { has_token: false },
  gitlab: { has_token: false },
};

export type DashboardState = {
  config: ConfigSummary | null;
  dashboard: Dashboard;
  operations: Map<string, Operation>;
  tokenStatus: TokenStatusResponse;
  error: string | null;
  refreshing: boolean;
  refresh: () => Promise<void>;
  saveToken: (provider: GitProvider, token: string) => Promise<boolean>;
  addOperation: (op: Operation) => void;
  dropOperations: (predicate: (op: Operation) => boolean) => void;
  setError: (message: string | null) => void;
};

/**
 * Owns dashboard + operation state. Operations arrive via the SSE stream
 * (`/api/operations/stream`) rather than per-operation polling; a terminal
 * transition triggers a dashboard refresh so the real codespace replaces the
 * in-flight card.
 */
export function useDashboard(showToast: ShowToast): DashboardState {
  const [config, setConfig] = useState<ConfigSummary | null>(null);
  const [dashboard, setDashboard] = useState<Dashboard>(emptyDashboard);
  const [operations, setOperations] = useState<Map<string, Operation>>(new Map());
  const [tokenStatus, setTokenStatus] = useState<TokenStatusResponse>(emptyTokenStatus);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const refreshSeqRef = useRef(0);
  const prevStatusRef = useRef<Map<string, string>>(new Map());

  const refresh = useCallback(async () => {
    const seq = refreshSeqRef.current + 1;
    refreshSeqRef.current = seq;
    setRefreshing(true);
    try {
      const result = await request<Dashboard>('/api/dashboard');
      if (seq !== refreshSeqRef.current) return;
      setError(null);
      setDashboard(result);
      setOperations(new Map((result.operations || []).map((op) => [op.id, op])));
    } catch (refreshError) {
      if (seq === refreshSeqRef.current) setError((refreshError as Error).message);
    } finally {
      if (seq === refreshSeqRef.current) setRefreshing(false);
    }
  }, []);

  const refreshTokens = useCallback(async () => {
    setTokenStatus(await request<TokenStatusResponse>('/api/provider-tokens'));
  }, []);

  const saveToken = useCallback(
    async (provider: GitProvider, token: string): Promise<boolean> => {
      const trimmed = token.trim();
      if (!trimmed) return false;
      try {
        const result = await request<TokenStatusResponse>(`/api/provider-tokens/${provider}`, {
          method: 'PUT',
          body: JSON.stringify({ token: trimmed }),
        });
        setTokenStatus(result);
        return true;
      } catch (saveError) {
        showToast((saveError as Error).message, 'danger');
        return false;
      }
    },
    [showToast],
  );

  const addOperation = useCallback((op: Operation) => {
    setOperations((current) => new Map(current).set(op.id, op));
  }, []);

  const dropOperations = useCallback((predicate: (op: Operation) => boolean) => {
    setOperations((current) => {
      const next = new Map(current);
      for (const [id, op] of current.entries()) if (predicate(op)) next.delete(id);
      return next;
    });
  }, []);

  // Initial load: config, tokens, dashboard.
  useEffect(() => {
    async function loadAll() {
      try {
        setError(null);
        setConfig(await request<ConfigSummary>('/api/config'));
        await refreshTokens();
        await refresh();
      } catch (loadError) {
        setError((loadError as Error).message);
      }
    }
    void loadAll();
  }, [refresh, refreshTokens]);

  // Live operation updates over SSE; refresh dashboard on terminal transitions.
  useEffect(() => {
    return openOperationStream((op) => {
      addOperation(op);
      const previous = prevStatusRef.current.get(op.id);
      prevStatusRef.current.set(op.id, op.status);
      if (previous === op.status) return;
      if (op.status === 'succeeded') {
        showToast(`Codespace ready: ${op.alias}`);
        void refresh();
      } else if (op.status === 'failed') {
        showToast(`Operation failed: ${op.alias}`, 'danger');
        void refresh();
      }
    });
  }, [addOperation, refresh, showToast]);

  return {
    config,
    dashboard,
    operations,
    tokenStatus,
    error,
    refreshing,
    refresh,
    saveToken,
    addOperation,
    dropOperations,
    setError,
  };
}
