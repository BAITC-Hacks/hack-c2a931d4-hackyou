import { describe, expect, it } from 'vitest';
import { addFiles, formatMoney } from './files';

const file = (name: string, size = 5) => new File(['x'.repeat(size)], name);

describe('parquet selection', () => {
  it('accepts files in any order and keeps previously selected files', () => {
    const first = addFiles({}, [file('edges.parquet')], 100);
    const all = addFiles(first, [file('TRANSACTIONS.parquet'), file('nodes.parquet')], 100);
    expect(Object.keys(all).sort()).toEqual(['edges', 'nodes', 'transactions']);
    expect(first.nodes).toBeUndefined();
  });
  it('rejects duplicates, unknown, empty and oversized files', () => {
    expect(() => addFiles({}, [file('nodes.parquet'), file('nodes.parquet')], 100)).toThrow(
      'дважды',
    );
    expect(() => addFiles({}, [file('other.parquet')], 100)).toThrow('Неизвестный');
    expect(() => addFiles({}, [file('nodes.parquet', 0)], 100)).toThrow('пуст');
    expect(() => addFiles({}, [file('nodes.parquet', 101)], 100)).toThrow('лимит');
  });
  it('never partially mutates selection when a later file fails', () => {
    const first = { nodes: file('nodes.parquet') };
    expect(() => addFiles(first, [file('edges.parquet'), file('bad.csv')], 100)).toThrow();
    expect(Object.keys(first)).toEqual(['nodes']);
  });
});

it('formats money above JS integer precision without rounding', () => {
  expect(formatMoney('9007199254740993.25').replace(/\s/g, '')).toBe('9007199254740993,25');
});
