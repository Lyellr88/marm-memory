import { describe, expect, it } from 'vitest';
import { sortProjectsByName } from './CodeContext';

describe('sortProjectsByName', () => {
  it('orders by the name the reader actually sees', () => {
    // The API returns index order, so the most recently touched lands last and
    // the list reads as arbitrary.
    const api = [
      { name: 'C-work-zeta', display_name: 'zeta' },
      { name: 'C-work-alpha', display_name: 'alpha' },
      { name: 'C-work-middle', display_name: 'Middle' },
    ];
    expect(sortProjectsByName(api).map((p) => p.display_name)).toEqual([
      'alpha',
      'Middle',
      'zeta',
    ]);
  });

  it('sorts on display_name, not the underlying id', () => {
    // Sorting on `name` would order the list by strings that are never shown:
    // here the ids are already ascending while the labels are not.
    const api = [
      { name: 'aaa', display_name: 'zebra' },
      { name: 'bbb', display_name: 'apple' },
    ];
    expect(sortProjectsByName(api).map((p) => p.display_name)).toEqual(['apple', 'zebra']);
  });

  it('falls back to name when there is no display_name', () => {
    const api = [{ name: 'zulu' }, { name: 'alpha', display_name: null }];
    expect(sortProjectsByName(api).map((p) => p.name)).toEqual(['alpha', 'zulu']);
  });

  it('does not mutate the caller array, which React state relies on', () => {
    const api = [{ name: 'b' }, { name: 'a' }];
    sortProjectsByName(api);
    expect(api.map((p) => p.name)).toEqual(['b', 'a']);
  });

  it('handles undefined', () => {
    expect(sortProjectsByName(undefined)).toEqual([]);
  });
});
