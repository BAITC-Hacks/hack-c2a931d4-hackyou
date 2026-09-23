import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  ArrowDownUp,
  ArrowUpRight,
  ChartNoAxesCombined,
  Download,
  Network,
  Search,
  SlidersHorizontal,
  X,
} from 'lucide-react';
import { api, type Analysis, type Dataset } from '../../api';
import { ErrorMessage } from '../../components/ErrorMessage';
import { count, date } from '../../format';
import { fileSize } from '../../files';
import { bucketLabel, evidenceText, percent, ringSegment, roles, score } from './presentation';
import { NodeDrawer } from './NodeDrawer';
import { GraphExplorer } from './GraphExplorer';

export function AnalysisDashboard({ run, dataset }: { run: Analysis; dataset: Dataset }) {
  const [filters, setFilters] = useState({
    search: '',
    role: '',
    bucket: '',
    sort: 'priority_desc',
    offset: 0,
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [view, setView] = useState<'overview' | 'network'>('overview');
  const [focus, setFocus] = useState(run.summary?.top_nodes[0]?.gid ?? '');
  const hasGraph = run.files.some((file) => file.name === 'graph_bundle.json');
  const overview = useQuery({
    queryKey: ['insights', run.id],
    queryFn: () => api.analysisInsights(run.id),
  });
  const params = new URLSearchParams({
    limit: '20',
    offset: String(filters.offset),
    sort: filters.sort,
  });
  if (filters.search) params.set('search', filters.search);
  if (filters.role) params.set('role', filters.role);
  if (filters.bucket !== '') params.set('bucket', filters.bucket);
  const nodes = useQuery({
    queryKey: ['analysis-nodes', run.id, params.toString()],
    queryFn: () => api.analysisNodes(run.id, params),
  });
  const selectRole = (role: string) =>
    setFilters({ ...filters, role: filters.role === role ? '' : role, offset: 0 });
  const selectBucket = (bucket: number) =>
    setFilters({
      ...filters,
      bucket: filters.bucket === String(bucket) ? '' : String(bucket),
      offset: 0,
    });
  const clear = () => setFilters({ ...filters, search: '', role: '', bucket: '', offset: 0 });
  const filtered = Boolean(filters.search || filters.role || filters.bucket);
  const summary = run.summary!;
  const stats = overview.data;
  let accumulated = 0;
  const slices = Object.entries(roles).map(([key, role]) => {
    const total = stats?.role_counts[key] ?? 0;
    const fraction = stats?.n_nodes ? total / stats.n_nodes : 0;
    const start = accumulated;
    accumulated += fraction;
    return { key, ...role, total, fraction, start };
  });
  const maxBucket = Math.max(1, ...(stats?.priority_buckets.map((bucket) => bucket.count) ?? []));
  return (
    <div className="analyst-dashboard">
      <nav className="analysis-view-switch" aria-label="Вид исследования">
        <button aria-pressed={view === 'overview'} onClick={() => setView('overview')}>
          <ChartNoAxesCombined size={16} /> Обзор и участники
        </button>
        <button
          aria-pressed={view === 'network'}
          onClick={() => setView('network')}
          disabled={!hasGraph}
          title={!hasGraph ? 'Граф доступен после запуска анализа движком' : undefined}
        >
          <Network size={16} /> Исследовать связи
        </button>
        <span>Снимок {run.id.slice(0, 8)}</span>
      </nav>
      <div className="overview-content" hidden={view !== 'overview'}>
        <div className="overview-strip">
          <div>
            <span>Участников в сети</span>
            <strong>{count(summary.n_nodes)}</strong>
            <small>Включая изолированные узлы</small>
          </div>
          <div>
            <span>Сообществ</span>
            <strong>{count(summary.n_clusters)}</strong>
            <small>По результатам движка</small>
          </div>
          <div>
            <span>Исходных узлов · seed</span>
            <strong>{count(dataset.quality.n_seed)}</strong>
            <small>Отправные точки исследования</small>
          </div>
          <div>
            <span>Переводов</span>
            <strong>{count(dataset.quality.n_transactions)}</strong>
            <small>
              {dataset.quality.period_start && dataset.quality.period_end
                ? `${date(dataset.quality.period_start)} — ${date(dataset.quality.period_end)}`
                : 'Период не указан'}
            </small>
          </div>
        </div>
        <ErrorMessage error={overview.error} />
        {overview.isPending && (
          <div className="panel dashboard-loading" role="status">
            Готовим обзор всех участников…
          </div>
        )}
        {stats && (
          <div className="insight-grid">
            <section className="panel chart-panel" aria-label="Распределение ролей">
              <div className="chart-heading">
                <span className="eyebrow">СТРУКТУРА СЕТИ</span>
                <span className="chart-tag">{count(stats.n_nodes)} узлов</span>
              </div>
              <h3>Какие роли преобладают</h3>
              <p className="micro">Нажмите на роль, чтобы отобрать участников в таблице.</p>
              <div className="role-chart">
                <svg viewBox="0 0 240 240" aria-hidden="true" className="donut-chart">
                  <circle cx="120" cy="120" r="90" fill="none" stroke="#edf0e9" strokeWidth="27" />
                  {slices
                    .filter((slice) => slice.total > 0)
                    .map((slice) => (
                      <path
                        key={slice.key}
                        d={ringSegment(slice.start, slice.fraction)}
                        fill={slice.color}
                        stroke="#fff"
                        strokeWidth={slices.filter((item) => item.total > 0).length > 1 ? 2 : 0}
                        opacity={filters.role && filters.role !== slice.key ? 0.25 : 1}
                        onClick={() => selectRole(slice.key)}
                      >
                        <title>
                          {slice.label}: {count(slice.total)} ·{' '}
                          {percent(slice.total, stats.n_nodes)}
                        </title>
                      </path>
                    ))}
                  <text x="120" y="115" className="donut-value">
                    {count(filters.role ? (stats.role_counts[filters.role] ?? 0) : stats.n_nodes)}
                  </text>
                  <text x="120" y="137" className="donut-caption">
                    {filters.role ? 'в выбранной роли' : 'участников'}
                  </text>
                </svg>
                <div className="role-legend">
                  {slices.map((slice) => (
                    <button
                      key={slice.key}
                      aria-pressed={filters.role === slice.key}
                      onClick={() => selectRole(slice.key)}
                      title={slice.description}
                    >
                      <i style={{ background: slice.color }} />
                      <span>
                        {slice.label}
                        <small>{percent(slice.total, stats.n_nodes)}</small>
                      </span>
                      <strong>{count(slice.total)}</strong>
                    </button>
                  ))}
                </div>
              </div>
              <p className="chart-footnote">
                Роли — гипотезы о функции участника в наблюдаемой сети.
              </p>
            </section>
            <section className="panel chart-panel" aria-label="Распределение приоритетов">
              <div className="chart-heading">
                <span className="eyebrow">ОЧЕРЕДНОСТЬ ПРОВЕРКИ</span>
                <span className="chart-tag">Шкала 0–1</span>
              </div>
              <h3>С кого начать проверку</h3>
              <p className="micro">Чем выше оценка, тем раньше движок предлагает проверить узел.</p>
              <div className="histogram" aria-label="Число участников по интервалам приоритета">
                {stats.priority_buckets.map((bucket) => (
                  <button
                    key={bucket.index}
                    className="histogram-column"
                    aria-pressed={filters.bucket === String(bucket.index)}
                    onClick={() => selectBucket(bucket.index)}
                    aria-label={`Приоритет ${bucketLabel(bucket.index)}: ${count(bucket.count)} участников`}
                  >
                    <span className="bar-track">
                      <span
                        className="bar-fill"
                        style={{
                          height: `${(bucket.count / maxBucket) * 100}%`,
                          background: ['#d3ddce', '#acc29f', '#7fa174', '#4d7e5d', '#235747'][
                            bucket.index
                          ],
                        }}
                      >
                        <b>{count(bucket.count)}</b>
                      </span>
                    </span>
                    <span className="bar-label">{bucketLabel(bucket.index)}</span>
                  </button>
                ))}
              </div>
              <p className="chart-footnote">
                Число узлов в каждом интервале. Правая граница не включена, кроме 1. Оценка не
                является вероятностью нарушения.
              </p>
            </section>
          </div>
        )}
        <section className="panel node-table-panel" aria-label="Участники анализа">
          <div className="node-table-heading">
            <div>
              <div className="eyebrow">ОТ ОБЗОРА К ДЕТАЛЯМ</div>
              <h3>
                Участники сети{' '}
                <span className="table-total">{nodes.data ? count(nodes.data.total) : '…'}</span>
              </h3>
              <p className="micro">
                Откройте GID, чтобы увидеть профиль и основания ролевой гипотезы.
              </p>
            </div>
            <SlidersHorizontal size={19} />
          </div>
          <div className="node-filters">
            <label className="node-search">
              <Search size={16} />
              <input
                aria-label="Поиск участника по GID"
                placeholder="Найти по GID…"
                value={filters.search}
                onChange={(event) =>
                  setFilters({ ...filters, search: event.target.value, offset: 0 })
                }
              />
            </label>
            <select
              aria-label="Фильтр по роли"
              value={filters.role}
              onChange={(event) => setFilters({ ...filters, role: event.target.value, offset: 0 })}
            >
              <option value="">Все роли</option>
              {slices.map((role) => (
                <option key={role.key} value={role.key}>
                  {role.label}
                </option>
              ))}
            </select>
            <label className="node-sort">
              <ArrowDownUp size={15} />
              <select
                aria-label="Порядок по приоритету"
                value={filters.sort}
                onChange={(event) =>
                  setFilters({ ...filters, sort: event.target.value, offset: 0 })
                }
              >
                <option value="priority_desc">Сначала высокий приоритет</option>
                <option value="priority_asc">Сначала низкий приоритет</option>
              </select>
            </label>
          </div>
          {filtered && (
            <div className="active-filters">
              <span>Выборка:</span>
              {filters.role && (
                <button onClick={() => selectRole(filters.role)}>
                  {roles[filters.role]?.label}
                  <X size={13} />
                </button>
              )}
              {filters.bucket !== '' && (
                <button onClick={() => selectBucket(Number(filters.bucket))}>
                  Приоритет {bucketLabel(Number(filters.bucket))}
                  <X size={13} />
                </button>
              )}
              {filters.search && <span>GID содержит «{filters.search}»</span>}
              <button className="reset-filters" onClick={clear}>
                Сбросить всё
              </button>
              <small>Диаграммы показывают весь набор</small>
            </div>
          )}
          <ErrorMessage error={nodes.error} />
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="Таблица участников, прокручивается горизонтально"
            aria-busy={nodes.isFetching}
          >
            <table className="node-table">
              <thead>
                <tr>
                  <th>Участник / GID</th>
                  <th>Ролевая гипотеза</th>
                  <th>Приоритет</th>
                  <th>Сообщество</th>
                  <th>Краткое основание</th>
                </tr>
              </thead>
              <tbody>
                {nodes.data?.items.map((node) => (
                  <tr key={node.gid}>
                    <td>
                      <button className="node-link" onClick={() => setSelected(node.gid)}>
                        <code>{node.gid}</code>
                        <ArrowUpRight size={14} />
                      </button>
                    </td>
                    <td>
                      <span className="role-pill">
                        <i style={{ background: roles[node.role]?.color }} />
                        {roles[node.role]?.label ?? node.role}
                      </span>
                    </td>
                    <td>
                      <span className="table-score">
                        <strong>{score(node.priority_score)}</strong>
                        <span>
                          <i style={{ width: `${node.priority_score * 100}%` }} />
                        </span>
                      </span>
                    </td>
                    <td>
                      <span className="cluster-label">#{node.cluster_id}</span>
                    </td>
                    <td className="node-reason">{evidenceText(node.evidence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {nodes.isPending && !nodes.error && (
            <div className="table-empty" role="status">
              Загружаем участников…
            </div>
          )}
          {nodes.data?.total === 0 && (
            <div className="table-empty">
              <Search size={22} />
              <strong>В этой выборке нет участников</strong>
              <span>Попробуйте другую роль, интервал приоритета или GID.</span>
              <button className="button secondary" onClick={clear}>
                Сбросить фильтры
              </button>
            </div>
          )}
          <div className="node-pagination">
            <span aria-live="polite">
              {nodes.data
                ? nodes.data.total
                  ? `${count(filters.offset + 1)}–${count(filters.offset + nodes.data.items.length)} из ${count(nodes.data.total)}`
                  : '0 участников'
                : '…'}
            </span>
            <div>
              <button
                className="button secondary"
                disabled={filters.offset === 0 || nodes.isPending}
                onClick={() => setFilters({ ...filters, offset: Math.max(0, filters.offset - 20) })}
              >
                Назад
              </button>
              <button
                className="button secondary"
                disabled={!nodes.data || filters.offset + 20 >= nodes.data.total}
                onClick={() => setFilters({ ...filters, offset: filters.offset + 20 })}
              >
                Далее
              </button>
            </div>
          </div>
        </section>
        <div className="report-details-grid">
          <details className="panel report-details">
            <summary>
              <Download size={17} /> Выгрузки и сведения о расчёте{' '}
              <span>{run.files.length} файлов</span>
            </summary>
            <p className="micro">
              {run.engine_label}
              {summary.elapsed_seconds != null && ` · ${score(summary.elapsed_seconds)} с`}
              {summary.model_backend && ` · ${summary.model_backend}`}
            </p>
            {summary.fallback_reason && <p className="micro">{summary.fallback_reason}</p>}
            <div className="export-links">
              {run.files.map((file) => (
                <a
                  key={file.name}
                  href={`/api/v1/analyses/${run.id}/exports/${file.name}`}
                  download
                >
                  <Download size={15} />
                  <span>
                    {file.name}
                    <small>{fileSize(file.size_bytes)}</small>
                  </span>
                </a>
              ))}
            </div>
          </details>
          <details className="panel report-details">
            <summary>
              Как читать результат <span>{summary.warnings.length} ограничений</span>
            </summary>
            <ul className="analysis-warnings">
              {summary.warnings.map((warning, index) => (
                <li key={index}>{warning}</li>
              ))}
            </ul>
            <div className="role-glossary">
              {slices.map((role) => (
                <p key={role.key}>
                  <strong>{role.label}.</strong> {role.description}
                </p>
              ))}
            </div>
          </details>
        </div>
      </div>
      {view === 'network' && focus && (
        <GraphExplorer analysisId={run.id} gid={focus} onSelect={setFocus} />
      )}
      {selected && (
        <NodeDrawer
          analysisId={run.id}
          gid={selected}
          onClose={() => setSelected(null)}
          onExplore={
            hasGraph
              ? () => {
                  setFocus(selected);
                  setSelected(null);
                  setView('network');
                }
              : undefined
          }
        />
      )}
    </div>
  );
}
