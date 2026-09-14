// @vitest-environment jsdom
import {afterEach, expect, it} from 'vitest';
import {cleanup, render, screen} from '@testing-library/react';
import CoachMarkdown from './CoachMarkdown';

afterEach(cleanup);
it('renders coach headings, emphasis, lists, links and nutrition tables', () => {
  render(<CoachMarkdown text={'## Dinner\n\nTry **chicken** with:\n\n- Rice\n- Broccoli\n\n[Menu](https://example.com/menu)\n\n| Food | Protein |\n| --- | --- |\n| Chicken | 30 g |'}/>);
  expect(screen.getByRole('heading', {name: 'Dinner'})).toBeTruthy();
  expect(screen.getByText('chicken').tagName).toBe('STRONG');
  expect(screen.getAllByRole('listitem')).toHaveLength(2);
  expect(screen.getByRole('link', {name: 'Menu'}).getAttribute('href')).toBe('https://example.com/menu');
  expect(screen.getByRole('table')).toBeTruthy();
  expect(screen.getByRole('cell', {name: '30 g'})).toBeTruthy();
});
it('does not turn raw HTML or unsafe links into executable content', () => {
  const {container} = render(<CoachMarkdown text={'<script>alert(1)</script>\n\n<img src="x" onerror="alert(1)">\n\n[unsafe](javascript:alert%281%29)'}/>);
  expect(container.querySelector('script, img')).toBeNull();
  expect(container.querySelector('a')?.getAttribute('href')).not.toMatch(/^javascript:/i);
});
