import { fetchAuthSession } from 'aws-amplify/auth';
import { config } from './config';

export class ApiError extends Error {
  constructor(message: string, public status: number, public code: string) { super(message); }
}
export async function api<T = any>(path: string, options: {method?: string; body?: unknown; version?: number; key?: string} = {}): Promise<T> {
  const token = (await fetchAuthSession()).tokens?.accessToken?.toString();
  if (!token) throw new ApiError('Please sign in again.', 401, 'unauthorized');
  const method = options.method || 'GET';
  const headers: Record<string, string> = {Authorization: `Bearer ${token}`};
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (options.version !== undefined) headers['If-Match'] = String(options.version);
  if (method === 'POST') headers['Idempotency-Key'] = options.key || crypto.randomUUID();
  const response = await fetch(config.apiUrl + path, {method, headers, body: options.body === undefined ? undefined : JSON.stringify(options.body)});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const fields = data.details?.map((d: any) => d.field?.join('.')).filter(Boolean).join(', ');
    throw new ApiError((data.message || `Request failed (${response.status})`) + (fields ? `: ${fields}` : '') + (response.status === 409 ? ' Refresh to load the latest version.' : ''), response.status, data.code || 'request_failed');
  }
  return data as T;
}
export const list = async (path: string) => {
  const items: any[] = [];
  let cursor: string | undefined;
  do {
    const page = await api(path + (cursor ? `${path.includes('?') ? '&' : '?'}cursor=${encodeURIComponent(cursor)}` : ''));
    items.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor);
  return items;
};
export function localDate(zone = Intl.DateTimeFormat().resolvedOptions().timeZone) {
  return new Intl.DateTimeFormat('en-CA', {timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
}
