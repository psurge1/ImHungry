// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
vi.mock('./api', () => ({api: vi.fn(), list: vi.fn(), localDate: () => '2026-09-14', ApiError: class extends Error {status = 500;}}));
import { api, list } from './api';
import App from './App';
beforeEach(() => {
  vi.resetAllMocks(); vi.mocked(list).mockResolvedValue([]);
  vi.mocked(api).mockImplementation(async path => path === '/v1/profile' ? {version: 0, configured: false} : {});
});
afterEach(cleanup);
function open() { render(<QueryClientProvider client={new QueryClient({defaultOptions: {queries: {retry: false}}})}><App onSignOut={() => {}}/></QueryClientProvider>); }
it('creates the initial profile using version zero and backend field names', async () => {
  open(); fireEvent.click(screen.getByRole('button', {name: 'Setup'}));
  const height = await screen.findByLabelText('Height (cm)');
  fireEvent.change(height, {target: {value: '178'}});
  fireEvent.change(screen.getByLabelText('Date of birth'), {target: {value: '1995-04-12'}});
  fireEvent.change(screen.getByLabelText('Sex used for BMR calculation'), {target: {value: 'male'}});
  fireEvent.change(screen.getByLabelText('Activity level'), {target: {value: 'lightly_active'}});
  fireEvent.change(screen.getByLabelText('Allergies (comma-separated)'), {target: {value: 'peanuts, shellfish'}});
  fireEvent.click(screen.getByRole('button', {name: 'Save profile'}));
  await waitFor(() => expect(api).toHaveBeenCalledWith('/v1/profile', expect.objectContaining({method: 'PATCH', version: 0,
    body: expect.objectContaining({height_cm: 178, date_of_birth: '1995-04-12', sex_for_bmr_equation: 'male', activity_context: {level: 'lightly_active'}, allergies: ['peanuts', 'shellfish']})})));
});
it('keeps the same message and request key when retrying an ambiguous failure', async () => {
  let attempts = 0;
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path === '/v1/conversations') return {conversation_id: 'one'};
    if (path.endsWith('/messages') && options?.method === 'POST') {
      if (++attempts === 1) throw new Error('Network unavailable');
      return {response: 'Hello'};
    }
    if (path.endsWith('/messages')) return {messages: []};
    return {version: 0, configured: false};
  });
  open(); fireEvent.click(screen.getByRole('button', {name: 'Coach'}));
  fireEvent.change(screen.getByLabelText('Your message'), {target: {value: 'Help with dinner'}});
  fireEvent.click(screen.getByRole('button', {name: 'Send message'}));
  await screen.findByText(/Network unavailable/);
  fireEvent.click(screen.getByRole('button', {name: 'Retry same message'}));
  await waitFor(() => expect(attempts).toBe(2));
  const calls = vi.mocked(api).mock.calls.filter(([p, o]) => p.endsWith('/messages') && o?.method === 'POST');
  expect(calls[0][1]?.key).toBeTruthy(); expect(calls[1][1]?.key).toBe(calls[0][1]?.key);
  expect(calls[1][1]?.body).toEqual(calls[0][1]?.body);
});
