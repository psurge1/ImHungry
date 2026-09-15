// @vitest-environment jsdom
import React from 'react';
import {afterEach, expect, it} from 'vitest';
import {cleanup, render, screen} from '@testing-library/react';
import ToolActivity from './ToolActivity';
afterEach(cleanup);
it('shows actual outcomes without treating unavailable data as success', () => {
  render(<ToolActivity items={[{name:'lookup_restaurant_menu',status:'unavailable'},{name:'estimate_food_nutrition',status:'failed'},{name:'log_food',status:'completed'},{name:'get_user_profile',status:'unconfirmed'}]}/>);
  expect(screen.getByText('Tool activity · 4')).toBeTruthy();
  for (const text of ['Look up restaurant menu','No data available','Failed','Completed','Result not confirmed']) expect(screen.getByText(text)).toBeTruthy();
});
it('does not invent activity for text-only replies', () => {
  const {container} = render(<ToolActivity/>);
  expect(container.textContent).toBe('');
});
