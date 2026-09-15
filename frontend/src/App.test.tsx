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
  const height = await screen.findByLabelText('Height (in)');
  fireEvent.change(height, {target: {value: '70'}});
  fireEvent.change(screen.getByLabelText('Date of birth'), {target: {value: '1995-04-12'}});
  fireEvent.change(screen.getByLabelText('Sex used for BMR calculation'), {target: {value: 'male'}});
  fireEvent.change(screen.getByLabelText('Activity level'), {target: {value: 'lightly_active'}});
  fireEvent.change(screen.getByLabelText('Allergies (comma-separated)'), {target: {value: 'peanuts, shellfish'}});
  fireEvent.click(screen.getByRole('button', {name: 'Save profile'}));
  await waitFor(() => expect(api).toHaveBeenCalledWith('/v1/profile', expect.objectContaining({method: 'PATCH', version: 0,
    body: expect.objectContaining({height_cm: 177.8, unit_system: 'imperial', date_of_birth: '1995-04-12', sex_for_bmr_equation: 'male', activity_context: {level: 'lightly_active'}, allergies: ['peanuts', 'shellfish']})})));
});
it('converts US weight inputs before calculating targets', async () => {
  vi.mocked(api).mockImplementation(async path => {
    if (path === '/v1/profile') return {version: 1, timezone: 'America/Chicago', height_cm: 180, date_of_birth: '1995-04-12', sex_for_bmr_equation: 'male', activity_context: {level: 'moderately_active'}, dietary_preferences: [], dietary_restrictions: [], allergies: [], disliked_foods: []};
    if (path === '/v1/nutrition-strategies/current') return {strategy: null};
    return {};
  });
  open(); fireEvent.click(screen.getByRole('button', {name: 'Setup'}));
  fireEvent.change(await screen.findByLabelText('Starting weight (lb)'), {target: {value: '155'}});
  fireEvent.change(screen.getByLabelText('Goal weight (lb, for weight loss)'), {target: {value: '145'}});
  fireEvent.change(screen.getByLabelText('Desired loss (lb/week, for weight loss)'), {target: {value: '0.5'}});
  fireEvent.click(screen.getByRole('button', {name: 'Calculate targets'}));
  await waitFor(() => expect(api).toHaveBeenCalledWith('/v1/nutrition-strategies/calculate', expect.objectContaining({body: {goal: {type: 'maintain_weight', baseline_weight_kg: 70.307, goal_weight_kg: 70.307, desired_rate_kg_per_week: 0}}})));
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
  fireEvent.click(screen.getByRole('button', {name: 'Today'}));
  fireEvent.click(screen.getByRole('button', {name: 'Coach'}));
  fireEvent.click(screen.getByRole('button', {name: 'Retry same message'}));
  await waitFor(() => expect(attempts).toBe(2));
  const calls = vi.mocked(api).mock.calls.filter(([p, o]) => p.endsWith('/messages') && o?.method === 'POST');
  expect(calls[0][1]?.key).toBeTruthy(); expect(calls[1][1]?.key).toBe(calls[0][1]?.key);
  expect(calls[1][1]?.body).toEqual(calls[0][1]?.body);
});

it('requests future meals and historical check-ins with explicit ranges', async () => {
  open(); fireEvent.click(screen.getByRole('button', {name: 'Plans'}));
  await waitFor(() => expect(list).toHaveBeenCalledWith('/v1/planned-meals?start_date=2026-09-14&end_date=2026-10-14'));
  fireEvent.click(screen.getByRole('button', {name: 'Progress'}));
  await waitFor(() => expect(list).toHaveBeenCalledWith('/v1/check-ins?start_date=2026-08-16&end_date=2026-09-14'));
});

it('sends explicit nulls when optional profile values are cleared', async () => {
  vi.mocked(api).mockImplementation(async path => path === '/v1/profile' ? {version:1,height_cm:180,date_of_birth:'1995-04-12',sex_for_bmr_equation:'male',activity_context:{level:'lightly_active'}} : {});
  open(); fireEvent.click(screen.getByRole('button', {name: 'Setup'}));
  fireEvent.change(await screen.findByLabelText('Height (in)'), {target:{value:''}});
  fireEvent.change(screen.getByLabelText('Date of birth'), {target:{value:''}});
  fireEvent.change(screen.getByLabelText('Sex used for BMR calculation'), {target:{value:''}});
  fireEvent.change(screen.getByLabelText('Activity level'), {target:{value:''}});
  fireEvent.click(screen.getByRole('button', {name:'Save profile'}));
  await waitFor(() => expect(api).toHaveBeenCalledWith('/v1/profile', expect.objectContaining({body:expect.objectContaining({height_cm:null,date_of_birth:null,sex_for_bmr_equation:null,activity_context:null})})));
});

it('retries a lost hydration response with the same body and request key', async () => {
  let attempts = 0;
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path === '/v1/hydration' && options?.method === 'POST' && ++attempts === 1) throw new Error('Response lost');
    return {version:0,configured:false};
  });
  open(); fireEvent.click(await screen.findByRole('button', {name:'Add drink'}));
  await screen.findByText('Response lost');
  fireEvent.click(screen.getByRole('button', {name:'Progress'}));
  fireEvent.click(screen.getByRole('button', {name:'Today'}));
  expect((screen.getByLabelText('Amount (fl oz)') as HTMLInputElement).closest('fieldset')?.disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', {name:'Retry same request'}));
  await waitFor(() => expect(attempts).toBe(2));
  const calls = vi.mocked(api).mock.calls.filter(([p,o]) => p === '/v1/hydration' && o?.method === 'POST');
  expect(calls[0][1]?.key).toBeTruthy();
  expect(calls[1][1]).toEqual(calls[0][1]);
});

it('invalidates a target proposal when its input changes', async () => {
  vi.mocked(api).mockImplementation(async path => path.endsWith('/calculate') ? {complete:true,targets:{energy_kcal:2200},calculation:{inputs:{weight_kg:70.3,height_cm:180,age_years:31,activity_level:'lightly_active'}},warnings:[]} : {version:0,configured:false});
  open(); fireEvent.click(screen.getByRole('button', {name:'Setup'}));
  fireEvent.change(await screen.findByLabelText('Starting weight (lb)'), {target:{value:'155'}});
  fireEvent.click(screen.getByRole('button', {name:'Calculate targets'}));
  await screen.findByRole('button', {name:'Accept these targets'});
  fireEvent.change(screen.getByLabelText('Starting weight (lb)'), {target:{value:'165'}});
  expect(screen.queryByRole('button', {name:'Accept these targets'})).toBeNull();
});

it('clears previous provenance and optional nutrients when manually replacing a food', async () => {
  vi.mocked(list).mockImplementation(async path => path.startsWith('/v1/food-log') ? [{entry_ref:'one',version:1,consumed_at:'2026-09-14T18:00:00Z',food:{display_name:'Old food',quantity:1,unit:'serving'},nutrition:{energy_kcal:100,protein_g:10,carbs_g:10,fat_g:2,sodium_mg:900},source:{type:'external_database',source_url:'https://example.com/old'}}] : []);
  open(); fireEvent.click(await screen.findByRole('button', {name:'Edit'}));
  fireEvent.change(screen.getByLabelText('Food', {exact:true}), {target:{value:'Replacement'}});
  fireEvent.click(screen.getByRole('button', {name:'Save changes'}));
  await waitFor(() => expect(api).toHaveBeenCalledWith('/v1/food-log/one', expect.objectContaining({body:expect.objectContaining({source:{type:'user_provided',provider:null,external_id:null,source_url:null,recipe_id:null,saved_food_id:null},nutrition:expect.objectContaining({sodium_mg:null,fiber_g:null})})})));
});

it('reuses conversation creation identity after a lost response', async () => {
  let attempts = 0;
  vi.mocked(api).mockImplementation(async (path, options) => {
    if(path === '/v1/conversations' && options?.method === 'POST') {
      if(++attempts === 1) throw new Error('Create response lost');
      return {conversation_id:'one'};
    }
    return {version:0,configured:false,messages:[]};
  });
  open(); fireEvent.click(screen.getByRole('button', {name:'Coach'}));
  fireEvent.change(screen.getByLabelText('Your message'), {target:{value:'Help with dinner'}});
  fireEvent.click(screen.getByRole('button', {name:'Send message'}));
  await screen.findByText(/Create response lost/);
  fireEvent.click(screen.getByRole('button', {name:'Retry same message'}));
  await waitFor(() => expect(attempts).toBe(2));
  const calls=vi.mocked(api).mock.calls.filter(([p,o])=>p==='/v1/conversations'&&o?.method==='POST');
  expect(calls[0][1]?.key).toBeTruthy(); expect(calls[1][1]).toEqual(calls[0][1]);
});


it('shows persisted tool activity beside the coach reply', async () => {
  vi.mocked(api).mockImplementation(async (path, options) => {
    if (path === '/v1/conversations') return {conversation_id:'one'};
    if (path.endsWith('/messages') && !options?.method) return {messages:[{role:'assistant',text:'Menu data was unavailable.',tool_activity:[{name:'lookup_restaurant_menu',status:'unavailable'}]}]};
    return {version:0,configured:false};
  });
  open(); fireEvent.click(screen.getByRole('button', {name:'Coach'}));
  fireEvent.change(screen.getByLabelText('Your message'), {target:{value:'Check this restaurant'}});
  fireEvent.click(screen.getByRole('button', {name:'Send message'}));
  expect(await screen.findByText('Look up restaurant menu')).toBeTruthy();
  expect(await screen.findByText('No data available')).toBeTruthy();
  expect(await screen.findByText('Menu data was unavailable.')).toBeTruthy();
});
