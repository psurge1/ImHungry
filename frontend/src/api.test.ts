import { beforeEach, expect, it, vi } from 'vitest';
vi.mock('aws-amplify/auth', () => ({fetchAuthSession: vi.fn()}));
import { fetchAuthSession } from 'aws-amplify/auth';
import { api, list } from './api';
beforeEach(() => { vi.resetAllMocks(); vi.mocked(fetchAuthSession).mockResolvedValue({tokens: {accessToken: {toString: () => 'test-access'}, idToken: {toString: () => 'test-id'}}} as any); });
it('sends access tokens, version and caller-provided retry keys', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response('{}', {status: 200})); vi.stubGlobal('fetch', fetcher);
  await api('/v1/conversations/one/messages', {method: 'POST', key: 'stable-retry', version: 3, body: {message: 'hello'}});
  expect(fetcher.mock.calls[0][1].headers).toEqual({Authorization: 'Bearer test-access', 'Idempotency-Key': 'stable-retry', 'If-Match': '3', 'Content-Type': 'application/json'});
});
it('does not send unauthenticated requests', async () => {
  vi.mocked(fetchAuthSession).mockResolvedValue({}); const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher);
  await expect(api('/v1/profile')).rejects.toThrow('sign in'); expect(fetcher).not.toHaveBeenCalled();
});
it('surfaces conflicts and does not automatically retry writes', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response('{"message":"Stale version"}', {status: 409})); vi.stubGlobal('fetch', fetcher);
  await expect(api('/v1/profile', {method: 'PATCH', version: 2, body: {}})).rejects.toThrow('Refresh'); expect(fetcher).toHaveBeenCalledTimes(1);
});
it('follows backend cursors without dropping entries', async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response('{"items":[1],"next_cursor":"a+b"}')).mockResolvedValueOnce(new Response('{"items":[2],"next_cursor":null}')); vi.stubGlobal('fetch', fetcher);
  expect(await list('/v1/food-log?start_date=2026-09-14')).toEqual([1, 2]);
  expect(fetcher.mock.calls[1][0]).toContain('&cursor=a%2Bb');
});
