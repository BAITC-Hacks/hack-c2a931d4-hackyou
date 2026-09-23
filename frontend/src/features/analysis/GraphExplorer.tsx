import { useEffect, useId, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowLeft, ArrowRight, Maximize2, Minus, Plus, UserRound, X } from 'lucide-react';
import { api, type Neighborhood } from '../../api';
import { ErrorMessage } from '../../components/ErrorMessage';
import { formatMoney } from '../../files';
import { count } from '../../format';
import { NodeDrawer } from './NodeDrawer';
import { roles } from './presentation';
import { flowLayout, type FlowDirection } from './flowLayout';

type Edge = Neighborhood['edges'][number];
const edgeKey = (edge: Edge) => `${edge.src}:${edge.dst}`;

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
  const [direction, setDirection] = useState<FlowDirection>('all');
  const [limit, setLimit] = useState(12);
  const [selection, setSelection] = useState<string | null>(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  useEffect(() => {
    panel.current?.focus({ preventScroll: true });
    panel.current?.scrollIntoView({ block: 'start' });
  }, []);
  const markerId = useId().replace(/:/g, '');
  const query = useQuery({
    queryKey: ['neighborhood', analysisId, gid, limit],
    queryFn: () => api.nodeNeighborhood(analysisId, gid, limit),
  });
  const profile = useQuery({
    queryKey: ['analysis-node', analysisId, gid],
    queryFn: () => api.analysisNode(analysisId, gid),
  });
  const graph = query.data;
  const layout = graph ? flowLayout(graph, direction) : null;
  const selected = graph?.edges.find((edge) => edgeKey(edge) === selection);
  const centerGraph = () => {
    const element = canvas.current;
    if (element) element.scrollTo((element.scrollWidth - element.clientWidth) / 2, 0);
  };
  useEffect(centerGraph, [gid, zoom, direction]);
  const select = (next: string) => {
    if (next === gid) {
      setProfileOpen(true);
      return;
    }
    setTrail([...trail, gid]);
    setSelection(null);
    onSelect(next);
    setZoom(1);
  };
  const activate = (event: React.KeyboardEvent, action: () => void) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      action();
    }
  };
  const focus = graph?.nodes.find((node) => node.gid === gid);
  return (
    <section
      ref={panel}
      tabIndex={-1}
      className="panel graph-panel"
      aria-label="Окружение участника"
    >
      <div className="graph-heading">
        <div>
          <h3>Откуда пришли и куда ушли деньги</h3>
          <p className="micro">
            В фокусе <code>{gid}</code> · один шаг по сети
          </p>
        </div>
        <div className="graph-actions">
          <button className="button secondary" onClick={() => setProfileOpen(true)}>
            <UserRound size={16} /> Профиль участника
          </button>
          <div className="graph-controls">
            <button
              className="icon-button"
              aria-label="Предыдущий участник"
              disabled={!trail.length}
              onClick={() => {
                onSelect(trail[trail.length - 1]);
                setTrail(trail.slice(0, -1));
                setZoom(1);
                setSelection(null);
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
      </div>
      {profile.data?.profile && (
        <div className="graph-totals">
          <div className="incoming">
            <span>Получено · всё окружение</span>
            <strong>{formatMoney(profile.data.profile.in_kzt)} ₸</strong>
            <small>
              {count(profile.data.profile.in_tx)} операций · {count(profile.data.profile.in_degree)}{' '}
              отправителей
            </small>
          </div>
          <div className="outgoing">
            <span>Отправлено · всё окружение</span>
            <strong>{formatMoney(profile.data.profile.out_kzt)} ₸</strong>
            <small>
              {count(profile.data.profile.out_tx)} операций ·{' '}
              {count(profile.data.profile.out_degree)} получателей
            </small>
          </div>
          <p>
            Суммы за весь период набора.
            <br />
            Одна стрелка объединяет все переводы в одном направлении.
          </p>
        </div>
      )}
      <div className="graph-toolbar">
        <div className="flow-switch" aria-label="Направление связей">
          {(
            [
              ['all', 'Все направления'],
              ['incoming', 'Только входящие'],
              ['outgoing', 'Только исходящие'],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              aria-pressed={direction === value}
              onClick={() => {
                setDirection(value);
                setSelection(null);
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <label>
          Соседей на схеме{' '}
          <select
            aria-label="Лимит соседей"
            value={limit}
            onChange={(event) => {
              setLimit(Number(event.target.value));
              setSelection(null);
            }}
          >
            <option value={6}>6</option>
            <option value={12}>12</option>
            <option value={20}>20</option>
          </select>
        </label>
      </div>
      <ErrorMessage error={query.error} />
      {query.isPending && (
        <div className="table-empty" role="status">
          Загружаем связи участника…
        </div>
      )}
      {graph && layout && (
        <>
          <div className="graph-scope">
            <span>
              Выбрано {count(graph.nodes.length - 1)} из {count(graph.total_neighbors)} соседей · на
              схеме {count(layout.flows.length + layout.loops.length)} из {count(graph.total_edges)}{' '}
              направленных связей
            </span>
            <span>Нажмите на сумму, чтобы раскрыть перевод</span>
          </div>
          {graph.total_neighbors > graph.nodes.length - 1 && (
            <p className="graph-limit">
              Показаны соседи с крупнейшими связями по сумме. Итоги выше учитывают всё окружение.
              Увеличьте лимит, чтобы увидеть больше соседей.
            </p>
          )}
          {selected && (
            <div className="selected-flow" role="region" aria-label="Выбранное направление">
              <div>
                <span>Отправитель</span>
                <button onClick={() => select(selected.src)}>{selected.src}</button>
              </div>
              <ArrowRight size={20} />
              <div>
                <span>Получатель</span>
                <button onClick={() => select(selected.dst)}>{selected.dst}</button>
              </div>
              <div>
                <strong>{formatMoney(selected.sum_kzt)} ₸</strong>
                <span>Операций: {count(selected.n_tx)} · за период набора</span>
              </div>
              <button
                className="icon-button"
                aria-label="Закрыть направление"
                onClick={() => setSelection(null)}
              >
                <X size={17} />
              </button>
            </div>
          )}
          <div
            className="graph-canvas"
            ref={canvas}
            tabIndex={0}
            role="region"
            aria-label="Граф связей, прокручивается по горизонтали на узком экране"
          >
            <svg
              viewBox={`0 0 1100 ${layout.height}`}
              style={{ width: `${zoom * 100}%`, minWidth: 1100 * zoom }}
              role="group"
              aria-label={`Направленные переводы участника ${gid}`}
            >
              <defs>
                {(['incoming', 'outgoing'] as const).map((value) => (
                  <marker
                    key={value}
                    id={`${markerId}-${value}`}
                    viewBox="0 0 10 10"
                    refX="9"
                    refY="5"
                    markerWidth="7"
                    markerHeight="7"
                    orient="auto"
                  >
                    <path
                      d="M 0 0 L 10 5 L 0 10 z"
                      fill={value === 'incoming' ? '#4c879c' : '#719c43'}
                    />
                  </marker>
                ))}
              </defs>
              <text x="200" y="32" className="flow-column-title">
                ОТПРАВИТЕЛИ →
              </text>
              <text x="900" y="32" className="flow-column-title">
                → ПОЛУЧАТЕЛИ
              </text>
              {layout.flows.map((flow) => (
                <path
                  key={edgeKey(flow.edge)}
                  d={flow.path}
                  className={`money-path ${flow.direction} ${selection === edgeKey(flow.edge) ? 'selected' : ''}`}
                  markerEnd={`url(#${markerId}-${flow.direction})`}
                />
              ))}
              {layout.flows.map((flow) => {
                const node = graph.nodes.find((node) => node.gid === flow.peer)!;
                const mutual = graph.edges.some(
                  (edge) => edge.src === flow.edge.dst && edge.dst === flow.edge.src,
                );
                return (
                  <g key={edgeKey(flow.edge)}>
                    <g
                      className={`edge-label ${flow.direction} ${selection === edgeKey(flow.edge) ? 'selected' : ''}`}
                      transform={`translate(${flow.labelX}, ${flow.y})`}
                      role="button"
                      tabIndex={0}
                      aria-label={`${flow.edge.src} → ${flow.edge.dst}: ${formatMoney(flow.edge.sum_kzt)} ₸, операций: ${flow.edge.n_tx}`}
                      aria-pressed={selection === edgeKey(flow.edge)}
                      onClick={() => setSelection(edgeKey(flow.edge))}
                      onKeyDown={(event) => activate(event, () => setSelection(edgeKey(flow.edge)))}
                    >
                      <rect x="-96" y="-39" width="192" height="70" rx="10" />
                      <text y="-10">{formatMoney(flow.edge.sum_kzt)} ₸</text>
                      <text y="15" className="edge-count">
                        Операций: {count(flow.edge.n_tx)}
                      </text>
                    </g>
                    <g
                      transform={`translate(${flow.nodeX}, ${flow.y})`}
                      className="graph-node"
                      role="button"
                      tabIndex={0}
                      aria-label={`Открыть участника ${node.gid}, ${roles[node.role]?.label}`}
                      onClick={() => select(node.gid)}
                      onKeyDown={(event) => activate(event, () => select(node.gid))}
                    >
                      <circle
                        className="node-circle"
                        r="36"
                        fill="#fff"
                        stroke={flow.direction === 'incoming' ? '#a7c6d0' : '#bacda4'}
                        strokeWidth="2"
                      />
                      <text className="graph-node-short" y="5">
                        …{node.gid.slice(-6)}
                      </text>
                      <text className="graph-gid" y="58">
                        {node.gid}
                      </text>
                      <text className="graph-role" y="77">
                        {roles[node.role]?.label ?? node.role}
                        {mutual ? ' · ↔' : ''}
                      </text>
                      <title>
                        GID {node.gid}
                        {mutual
                          ? ' · Есть переводы в обе стороны; этот участник показан в двух колонках.'
                          : ''}
                      </title>
                    </g>
                  </g>
                );
              })}
              <g
                transform={`translate(550, ${layout.focusY})`}
                className="graph-node focused"
                role="button"
                tabIndex={0}
                aria-label={`Профиль участника ${gid}`}
                onClick={() => setProfileOpen(true)}
                onKeyDown={(event) => activate(event, () => setProfileOpen(true))}
              >
                <circle r="61" fill="#e8f1d7" />
                <circle
                  className="node-circle"
                  r="49"
                  fill="#8dce46"
                  stroke="#72b535"
                  strokeWidth="2"
                />
                <text className="graph-focus-label" y="-77">
                  В ФОКУСЕ
                </text>
                <text className="graph-node-short" y="5">
                  …{gid.slice(-6)}
                </text>
                <text className="graph-gid" y="87">
                  {gid}
                </text>
                <text className="graph-role" y="108">
                  {focus && roles[focus.role]?.label}
                </text>
              </g>
            </svg>
          </div>
          {layout.loops.map((edge) => (
            <button
              className="self-transfer"
              key={edgeKey(edge)}
              onClick={() => setSelection(edgeKey(edge))}
            >
              ↻ Переводы себе · {formatMoney(edge.sum_kzt)} ₸ · операций: {count(edge.n_tx)}
            </button>
          ))}
          {layout.flows.length === 0 && layout.loops.length === 0 && (
            <p className="graph-limit">
              {graph.total_edges === 0
                ? 'У участника нет наблюдаемых переводов в этом наборе.'
                : 'В выбранном направлении у показанных соседей нет связей. Переключите направление или увеличьте лимит.'}
            </p>
          )}
          <div className="graph-footer">
            <span>
              <i /> Выбранный участник
            </span>
            <span>↔ Один и тот же GID в двух колонках — переводы в обе стороны</span>
            <span>Узел → исследовать его связи · центр → профиль</span>
          </div>
          <details className="flow-table">
            <summary>
              Все показанные направления списком · {layout.flows.length + layout.loops.length}
            </summary>
            <p className="micro">
              Полные GID — идентификаторы участников. Сумма объединяет операции за весь период
              набора.
            </p>
            {[...layout.flows.map((flow) => flow.edge), ...layout.loops].map((edge) => (
              <button key={edgeKey(edge)} onClick={() => setSelection(edgeKey(edge))}>
                <code>
                  {edge.src} → {edge.dst}
                </code>
                <strong>{formatMoney(edge.sum_kzt)} ₸</strong>
                <span>Операций: {count(edge.n_tx)}</span>
              </button>
            ))}
          </details>
          <p className="graph-disclaimer">
            На схеме наблюдаемые переводы, а роли — гипотезы движка. Связь не устанавливает движение
            одних и тех же денег.
          </p>
        </>
      )}
      {profileOpen && (
        <NodeDrawer analysisId={analysisId} gid={gid} onClose={() => setProfileOpen(false)} />
      )}
    </section>
  );
}
