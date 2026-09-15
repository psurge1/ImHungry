import {expect, it} from 'vitest';
import {dateAtNoon, shiftDate} from './dates';

it.each(['Pacific/Kiritimati', 'Etc/GMT+12', 'America/Chicago', 'Asia/Kolkata'])(
  'historical timestamps stay on the requested profile-local day in %s', zone => {
    for (const day of ['2026-03-08', '2026-11-01', '2026-09-14']) {
      const instant = new Date(dateAtNoon(day, zone));
      expect(new Intl.DateTimeFormat('en-CA', {timeZone: zone, year:'numeric',month:'2-digit',day:'2-digit'}).format(instant)).toBe(day);
      expect(new Intl.DateTimeFormat('en-US', {timeZone: zone,hour:'numeric',hourCycle:'h23'}).format(instant)).toBe('12');
    }
  });
it('shifts calendar ranges across month and year boundaries', () => {
  expect(shiftDate('2026-01-01', -1)).toBe('2025-12-31');
  expect(shiftDate('2026-09-15', -29)).toBe('2026-08-17');
});
