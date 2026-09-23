import { describe, expect, it } from 'vitest';
import type { Neighborhood } from '../../api';
import { flowLayout } from './flowLayout';

const focus = '100000003115284100';
const graph: Neighborhood = {
  focus,
  nodes: [],
  total_neighbors: 9,
  total_edges: 11,
  edges: [
    ...Array.from({ length: 8 }, (_, i) => ({
      src: `10000000000000000${i}`,
      dst: focus,
      sum_kzt: '100.25',
      n_tx: 2,
    })),
    { src: focus, dst: '100000000000000000', sum_kzt: '30.50', n_tx: 1 },
    { src: focus, dst: '100000000000000009', sum_kzt: '90', n_tx: 1 },
    { src: focus, dst: focus, sum_kzt: '10', n_tx: 1 },
  ],
};

describe('money flow layout', () => {
  it('keeps every directed edge, including reciprocal transfers and self-loops', () => {
    const result = flowLayout(graph, 'all');
    expect(result.flows).toHaveLength(10);
    expect(result.loops).toEqual([graph.edges[10]]);
    const reciprocal = result.flows.filter((f) => f.peer === '100000000000000000');
    expect(reciprocal.map((f) => f.direction)).toEqual(['incoming', 'outgoing']);
    for (const flow of result.flows) {
      expect(flow.edge).toBe(
        graph.edges.find((e) => e.src === flow.edge.src && e.dst === flow.edge.dst),
      );
      expect(flow.direction === 'incoming' ? flow.nodeX < 550 : flow.nodeX > 550).toBe(true);
      expect(flow.path.startsWith(flow.direction === 'incoming' ? 'M153,' : 'M602,')).toBe(true);
    }
  });
  it('leaves enough space between labels and full identifiers even with asymmetric degree', () => {
    const { flows, height } = flowLayout(graph, 'all');
    for (const direction of ['incoming', 'outgoing']) {
      const rows = flows.filter((f) => f.direction === direction);
      for (let i = 1; i < rows.length; i++)
        expect(rows[i].y - rows[i - 1].y).toBeGreaterThanOrEqual(130);
      for (const row of rows) {
        expect(row.y - 39).toBeGreaterThan(32);
        expect(row.y + 77).toBeLessThan(height);
      }
    }
  });
  it('filters directions without losing reciprocal data or isolated focus', () => {
    expect(flowLayout(graph, 'incoming').flows).toHaveLength(8);
    expect(flowLayout(graph, 'outgoing').flows).toHaveLength(2);
    expect(flowLayout({ ...graph, edges: [] }, 'all').flows).toEqual([]);
  });
});
