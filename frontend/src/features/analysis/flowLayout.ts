import type { Neighborhood } from '../../api';

export type FlowDirection = 'all' | 'incoming' | 'outgoing';

// Labels have separate horizontal lanes before the curves converge. Reciprocal peers
// appear on both sides with the same GID: no direction is reversed or combined.
export function flowLayout(graph: Neighborhood, direction: FlowDirection) {
  const incoming = graph.edges.filter((e) => e.dst === graph.focus && e.src !== graph.focus);
  const outgoing = graph.edges.filter((e) => e.src === graph.focus && e.dst !== graph.focus);
  const left = direction === 'outgoing' ? [] : incoming;
  const right = direction === 'incoming' ? [] : outgoing;
  const height = Math.max(480, Math.max(left.length, right.length) * 140 + 95);
  const focusY = height / 2;
  const flows = (
    [
      ['incoming', left],
      ['outgoing', right],
    ] as const
  ).flatMap(([side, edges]) =>
    edges.map((edge, index) => {
      const y = (height - edges.length * 140) / 2 + index * 140 + 40;
      const inbound = side === 'incoming';
      return {
        edge,
        direction: side,
        peer: inbound ? edge.src : edge.dst,
        y,
        nodeX: inbound ? 115 : 985,
        labelX: inbound ? 305 : 795,
        path: inbound
          ? `M153,${y} L415,${y} C465,${y} 458,${focusY} 498,${focusY}`
          : `M602,${focusY} C642,${focusY} 635,${y} 685,${y} L946,${y}`,
      };
    }),
  );
  return { height, focusY, flows, loops: graph.edges.filter((e) => e.src === e.dst) };
}
