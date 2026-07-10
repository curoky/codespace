import { useCallback, useState } from 'react';

import type { Toast } from '../types';

const TOAST_TTL_MS = 3500;

export type ShowToast = (message: string, tone?: Toast['tone']) => void;

export function useToast(): {
  toasts: Toast[];
  showToast: ShowToast;
  dismissToast: (id: number) => void;
} {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismissToast = useCallback((id: number) => {
    setToasts((items) => items.filter((item) => item.id !== id));
  }, []);

  const showToast = useCallback<ShowToast>(
    (message, tone = 'success') => {
      const id = Date.now() + Math.random();
      setToasts((items) => [...items, { id, message, tone }]);
      window.setTimeout(() => dismissToast(id), TOAST_TTL_MS);
    },
    [dismissToast],
  );

  return { toasts, showToast, dismissToast };
}
