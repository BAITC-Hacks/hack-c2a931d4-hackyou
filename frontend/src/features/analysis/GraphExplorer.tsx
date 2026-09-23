import { useEffect, useId, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, Maximize2, Minus, Plus } from 'lucide-react';
import { api } from '../../api';
import { ErrorMessage } from '../../components/ErrorMessage';
import { formatMoney } from '../../files';
import { count } from '../../format';
import { NodeProfile } from './NodeDrawer';
import { roles } from './presentation';

export function GraphExplorer({
  analysisId,
  gid,
  onSelect,
}: {
  analysisId: string;
  gid: string;
  onSelect: (gid: string) => void;
}) {
  const [trail, setTrail] = useState<string[]>([]);
  const [zoom, setZoom] = useState(1);
  const panel = useRef<HTMLElement>(null);
  const profilePanel = useRef<HTMLElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  useEffect(() => {
    panel.current?.focus({ preventScroll: true });
    panel.current?.scrollIntoView({ block: 'start' });
  }, []);
  useEffect(() => {
    profilePanel.current?.scrollTo(0, 0);
  }, [gid]);
  const markerId = useId().replace(/:/g, '');
  const query = useQuery({
    queryKey: ['neighborhood', analysisId, gid],
    queryFn: () => api.nodeNeighborhood(analysisId, gid),
  });
  const graph = query.data;
  const centerGraph = () => {
    const element = canvas.current;
    if (element) element.scrollTo((element.scrollWidth - element.clientWidth) / 2, 0);
  };
  useEffect(centerGraph, [graph?.focus, zoom]);
  const incoming =
    graph?.nodes.filter(
      (node) =>
        node.gid !== gid && graph.edges.some((edge) => edge.src === node.gid && edge.dst === gid),
    ) ?? [];
  const outgoing =
    graph?.nodes.filter(
      (node) => node.gid !== gid && !incoming.some((item) => item.gid === node.gid),
    ) ?? [];
  // Balance the columns for readable labels; arrowheads, not position, encode direction.
  const ordered = [...incoming, ...outgoing];
  const midpoint = Math.ceil(ordered.length / 2);
  const left = ordered.slice(0, midpoint);
  const right = ordered.slice(midpoint);
  const height = Math.max(500, Math.max(left.length, right.length) * 110 + 80);
  const positions = new Map<string, { x: number; y: number }>([[gid, { x: 450, y: height / 2 }]]);
  for (const [items, x] of [
    [left, 135],
    [right, 765],
  ] as const) {
    items.forEach((node, index) =>
      positions.set(node.gid, { x, y: ((index + 1) * height) / (items.length + 1) }),
    );
  }
  const select = (next: string) => {
    if (next !== gid) {
      setTrail([...trail, gid]);
      onSelect(next);
      setZoom(1);
    }
  };
  return (
    <div className="graph-workspace">
      <section
        ref={panel}
        tabIndex={-1}
        className="panel graph-panel"
        aria-label="Окружение участника"
      >
        <div className="graph-heading">
          <div>
            <h3>Как связаны переводы?</h3>
            <p className="micro">
              В фокусе <code>{gid}</code> · один шаг по сети
            </p>
          </div>
          <div className="graph-controls">
            <button
              className="icon-button"
              aria-label="Предыдущий участник"
              disabled={!trail.length}
              onClick={() => {
                onSelect(trail[trail.length - 1]);
                setTrail(trail.slice(0, -1));
                setZoom(1);
              }}
            >
              <ArrowLeft size={17} />
            </button>
            <button
              className="icon-button"
              aria-label="Уменьшить граф"
              disabled={zoom <= 1}
              onClick={() => setZoom(Math.max(1, zoom - 0.25))}
            >
              <Minus size={16} />
            </button>
            <button
              className="icon-button"
              aria-label="Увеличить граф"
              disabled={zoom >= 2}
              onClick={() => setZoom(Math.min(2, zoom + 0.25))}
            >
              <Plus size={16} />
            </button>
            <button
              className="icon-button"
              aria-label="Сбросить масштаб"
              onClick={() => {
                setZoom(1);
                centerGraph();
              }}
            >
              <Maximize2 size={16} />
            </button>
          </div>
        </div>
        <ErrorMessage error={query.error} />
        {query.isPending && (
          <div className="table-empty" role="status">
            Загружаем связи участника…
          </div>
        )}
        {graph && (
          <>
            <div className="graph-scope">
              <span>
                Показано {count(graph.nodes.length - 1)} из {count(graph.total_neighbors)} соседей ·{' '}
                {count(graph.edges.length)} из {count(graph.total_edges)} связей
              </span>
              <span>Стрелка — направление перевода</span>
            </div>
            {graph.total_neighbors > graph.nodes.length - 1 && (
              <p className="graph-limit">
                Для читаемости выбраны 12 соседей с крупнейшими отдельными связями по сумме. Профиль
                справа учитывает всё окружение.
              </p>
            )}
            <div
              className="graph-canvas"
              ref={canvas}
              tabIndex={0}
              role="region"
              aria-label="Граф связей, прокручивается при увеличении"
            >
              <svg
                viewBox={`0 0 900 ${height}`}
                style={{ width: `${zoom * 100}%`, minWidth: 660 * zoom }}
                role="group"
                aria-label={`Направленные переводы участника ${gid}`}
              >
                <defs>
                  <marker
                    id={markerId}
                    viewBox="0 0 10 10"
                    refX="8"
                    refY="5"
                    markerWidth="6"
                    markerHeight="6"
                    orient="auto-start-reverse"
                  >
                    <path d="M 0 0 L 10 5 L 0 10 z" fill="#7a9c66" />
                  </marker>
                </defs>
                {graph.edges.map((edge) => {
                  const source = positions.get(edge.src)!;
                  const target = positions.get(edge.dst)!;
                  const self = edge.src === edge.dst;
                  const dx = target.x - source.x,
                    dy = target.y - source.y;
                  const distance = Math.hypot(dx, dy) || 1;
                  const start = {
                    x: source.x + (dx / distance) * 36,
                    y: source.y + (dy / distance) * 36,
                  };
                  const end = {
                    x: target.x - (dx / distance) * 39,
                    y: target.y - (dy / distance) * 39,
                  };
                  const both =
                    !self &&
                    graph.edges.some((item) => item.src === edge.dst && item.dst === edge.src);
                  const cx = (start.x + end.x) / 2 - (both ? (dy / distance) * 48 : 0);
                  const cy = (start.y + end.y) / 2 + (both ? (dx / distance) * 48 : 0);
                  const path = self
                    ? `M${source.x - 22},${source.y - 26} C${source.x - 90},${source.y - 125} ${source.x + 90},${source.y - 125} ${source.x + 22},${source.y - 30}`
                    : `M${start.x},${start.y} Q${cx},${cy} ${end.x},${end.y}`;
                  const labelX = self ? source.x : (start.x + 2 * cx + end.x) / 4;
                  const labelY = self ? source.y - 99 : (start.y + 2 * cy + end.y) / 4;
                  return (
                    <g key={`${edge.src}-${edge.dst}`}>
                      <path
                        d={path}
                        fill="none"
                        stroke="#88a974"
                        strokeWidth="2"
                        markerEnd={`url(#${markerId})`}
                      />
                      <g className="edge-label" transform={`translate(${labelX}, ${labelY})`}>
                        <rect x="-70" y="-21" width="140" height="34" rx="5" />
                        <text y="-6">{formatMoney(edge.sum_kzt)} ₸</text>
                        <text y="9" className="edge-count">
                          {count(edge.n_tx)} переводов
                        </text>
                      </g>
                      <title>
                        {edge.src} → {edge.dst}: {formatMoney(edge.sum_kzt)} ₸ · {edge.n_tx}{' '}
                        переводов
                      </title>
                    </g>
                  );
                })}
                {graph.nodes.map((node) => {
                  const point = positions.get(node.gid)!;
                  const focus = node.gid === gid;
                  return (
                    <g
                      key={node.gid}
                      transform={`translate(${point.x}, ${point.y})`}
                      className={`graph-node ${focus ? 'focused' : ''}`}
                      role="button"
                      tabIndex={0}
                      aria-label={`${focus ? 'Выбранный участник' : 'Открыть участника'} ${node.gid}, ${roles[node.role]?.label}`}
                      aria-pressed={focus}
                      onClick={() => select(node.gid)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault();
                          select(node.gid);
                        }
                      }}
                    >
                      {focus && <circle r="43" fill="#e8f1d7" />}
                      <circle
                        className="node-circle"
                        r="33"
                        fill={focus ? '#8dce46' : '#fff'}
                        stroke={focus ? '#72b535' : '#c2cdbd'}
                        strokeWidth="1.5"
                      />
                      <text className="graph-node-short" y="5">
                        …{node.gid.slice(-7)}
                      </text>
                      <text className="graph-gid" y="58">
                        {node.gid}
                      </text>
                      <text className="graph-role" y="75">
                        {roles[node.role]?.label ?? node.role}
                      </text>
                      {focus && (
                        <text className="graph-focus-label" y="-55">
                          В ФОКУСЕ
                        </text>
                      )}
                      <title>GID {node.gid}</title>
                    </g>
                  );
                })}
              </svg>
            </div>
            {graph.edges.length === 0 && (
              <p className="graph-limit">
                У участника нет наблюдаемых входящих и исходящих переводов в этом наборе.
              </p>
            )}
            <div className="graph-footer">
              <span>
                <i /> Выбранный участник
              </span>
              <span>Нажмите на соседний узел, чтобы продолжить исследование</span>
            </div>
            <p className="graph-disclaimer">
              Связь показывает наблюдаемые переводы. Она не устанавливает движение одних и тех же
              денег.
            </p>
          </>
        )}
      </section>
      <aside
        ref={profilePanel}
        className="panel graph-profile"
        aria-label="Профиль выбранного участника"
      >
        <header>
          <div className="eyebrow">ВЫБРАННЫЙ УЧАСТНИК</div>
          <h3>GID {gid}</h3>
        </header>
        <NodeProfile key={gid} analysisId={analysisId} gid={gid} />
      </aside>
    </div>
  );
}
