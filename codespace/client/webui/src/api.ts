export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  const body = response.headers.get('content-type')?.includes('application/json')
    ? await response.json()
    : {};
  if (!response.ok) throw new Error(errorMessage(body, response.status));
  return body as T;
}

function errorMessage(body: unknown, status: number): string {
  if (!body || typeof body !== 'object') return `HTTP ${status}`;
  const data = body as { error?: unknown; detail?: unknown };
  if (typeof data.error === 'string') return data.error;
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail
      .map((item) => {
        if (!item || typeof item !== 'object') return String(item);
        const detail = item as { loc?: unknown[]; msg?: unknown; type?: unknown };
        const loc = Array.isArray(detail.loc) ? detail.loc.join('.') : '';
        const msg = detail.msg || detail.type || 'validation error';
        return loc ? `${loc}: ${msg}` : String(msg);
      })
      .join('; ');
  }
  return `HTTP ${status}`;
}
