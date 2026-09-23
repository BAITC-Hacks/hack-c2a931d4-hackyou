import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { FileUp, Loader2, Play, X } from 'lucide-react';
import { api, ApiError, type Analysis, type AnalysisStatus, type Dataset } from '../../api';
import { ErrorMessage } from '../../components/ErrorMessage';
import { date } from '../../format';
import { fileSize } from '../../files';
import { AnalysisDashboard } from './AnalysisDashboard';

const statusText: Record<AnalysisStatus, string> = {
  queued: 'В очереди',
  running: 'Анализ сети',
  validating: 'Проверка результатов',
  succeeded: 'Готово',
  failed: 'Ошибка',
  cancelled: 'Отменён',
  interrupted: 'Прерван',
};
const active = (run?: Analysis) =>
  Boolean(run && ['queued', 'running', 'validating'].includes(run.status));
const resultNames = ['nodes_roles', 'clusters', 'top_nodes'];

export function AnalysisPanel({ dataset }: { dataset: Dataset }) {
  const cache = useQueryClient();
  const [selected, setSelected] = useState('');
  const [offset, setOffset] = useState(0);
  const [files, setFiles] = useState<Record<string, File>>({});
  const [fileError, setFileError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const operationKey = useRef<string | null>(null);
  const operationSource = useRef('');
  const health = useQuery({ queryKey: ['health'], queryFn: api.health });
  const history = useQuery({
    queryKey: ['analyses', dataset.id, offset],
    queryFn: () => api.listAnalyses(dataset.id, offset),
    refetchInterval: (query) => (query.state.data?.items.some(active) ? 1500 : false),
  });
  const id = selected || history.data?.items[0]?.id || '';
  const detail = useQuery({
    queryKey: ['analysis', id],
    queryFn: () => api.getAnalysis(id),
    enabled: Boolean(id),
    refetchInterval: (query) => (active(query.state.data) ? 1000 : false),
  });
  const run = detail.data;
  const events = useQuery({
    queryKey: ['analysis-events', id, run?.status],
    queryFn: () => api.analysisEvents(id),
    enabled: Boolean(id),
    refetchInterval: active(run) ? 1000 : false,
  });
  const invalidate = () => {
    void cache.invalidateQueries({ queryKey: ['analyses', dataset.id] });
    void cache.invalidateQueries({ queryKey: ['analysis'] });
    void cache.invalidateQueries({ queryKey: ['analysis-events'] });
  };
  const mutation = useMutation({
    mutationFn: (source: 'engine' | 'files') => {
      if (operationSource.current !== source) operationKey.current = null;
      operationSource.current = source;
      operationKey.current ??= crypto.randomUUID();
      return source === 'engine'
        ? api.startAnalysis(dataset.id, operationKey.current)
        : api.importResults(dataset.id, operationKey.current, files);
    },
    onSuccess: (value) => {
      setSelected(value.id);
      setOffset(0);
      setFiles({});
      operationKey.current = null;
      invalidate();
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status !== 0) operationKey.current = null;
      invalidate();
    },
    // Keep the operation key on ambiguous network failures to prevent duplicate jobs.
  });
  const cancel = useMutation({ mutationFn: () => api.cancelAnalysis(id), onSuccess: invalidate });
  const busy = mutation.isPending || history.data?.items.some(active) || active(run);
  const summary = run?.status === 'succeeded' ? run.summary : null;
  const selectFiles = (incoming: File[]) => {
    try {
      const next = { ...files };
      for (const file of incoming) {
        const key = file.name.replace(/\.csv$/i, '').toLowerCase();
        if (!/\.csv$/i.test(file.name) || !resultNames.includes(key))
          throw new Error('Выберите nodes_roles.csv, clusters.csv и top_nodes.csv.');
        if (!file.size || file.size > (health.data?.limits.max_file_bytes ?? 50 * 1024 * 1024))
          throw new Error(`${file.name}: пустой файл или превышен лимит размера.`);
        next[key] = file;
      }
      setFiles(next);
      setFileError(null);
      mutation.reset();
      operationKey.current = null;
    } catch (error) {
      setFileError((error as Error).message);
    }
  };
  return (
    <section id="analysis" className="analysis-section" aria-label="Анализ сети">
      <div className={`analysis-heading ${summary ? 'has-results' : ''}`}>
        <div>
          <div className="eyebrow">АНАЛИЗ СЕТИ</div>
          <h2>Исследование финансовой сети</h2>
          <p className="muted">Роли, сообщества и приоритеты для выбранного набора.</p>
        </div>
        <button
          className="button primary"
          disabled={busy || !health.data?.capabilities.analysis}
          onClick={() => mutation.mutate('engine')}
        >
          {busy ? <Loader2 size={17} className="spin" /> : <Play size={17} />}
          {busy ? 'Выполняется…' : 'Запустить анализ'}
        </button>
      </div>
      {!health.data?.capabilities.analysis && (
        <p className="micro">
          Окружение движка не подключено. Можно загрузить готовые результаты ниже.
        </p>
      )}
      <ErrorMessage error={mutation.error || cancel.error || history.error || detail.error} />
      <div className={`analysis-layout ${summary ? 'has-results' : ''}`}>
        <details className="panel analysis-history">
          <summary>
            История запусков и импорт CSV <span>{history.data?.total ?? 0} запусков</span>
          </summary>
          <div className="history-content">
            <h3>
              История запусков <small>{history.data?.total ?? 0}</small>
            </h3>
            {history.isPending && <p className="micro">Загружаем историю…</p>}
            {history.data?.total === 0 && (
              <p className="micro">
                Запусков ещё нет. Каждый результат сохраняется отдельно и остаётся доступен после
                перезапуска.
              </p>
            )}
            {history.data?.items.map((item) => (
              <button
                key={item.id}
                className={`run-card ${item.id === id ? 'selected' : ''}`}
                onClick={() => setSelected(item.id)}
              >
                <span>
                  <strong>{item.source === 'command' ? 'Анализ движком' : 'Импорт CSV'}</strong>
                  <small>{item.id.slice(0, 8)}</small>
                </span>
                <span>
                  <small>{date(item.created_at)}</small>
                  <b className={`run-status ${item.status}`}>{statusText[item.status]}</b>
                </span>
              </button>
            ))}
            {(history.data?.total ?? 0) > 10 && (
              <div className="analysis-actions">
                <button
                  className="button secondary"
                  disabled={offset === 0}
                  onClick={() => {
                    setOffset(offset - 10);
                    setSelected('');
                  }}
                >
                  Назад
                </button>
                <button
                  className="button secondary"
                  disabled={offset + 10 >= (history.data?.total ?? 0)}
                  onClick={() => {
                    setOffset(offset + 10);
                    setSelected('');
                  }}
                >
                  Далее
                </button>
              </div>
            )}
            <details className="result-import">
              <summary>Загрузить готовые CSV</summary>
              <p className="micro">
                Три выгрузки для этого набора: роли узлов, кластеры и рейтинг. Проверим их по
                исходным parquet.
              </p>
              <input
                ref={input}
                type="file"
                accept=".csv"
                multiple
                className="sr-only"
                aria-label="Выбрать CSV результатов"
                onChange={(event) => {
                  selectFiles(Array.from(event.target.files ?? []));
                  event.target.value = '';
                }}
              />
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => input.current?.click()}
              >
                <FileUp size={16} />
                Выбрать CSV
              </button>
              {resultNames.map((key) => (
                <div className="result-file" key={key}>
                  <span>
                    {key}.csv<small>{files[key] ? fileSize(files[key].size) : 'Ожидается'}</small>
                  </span>
                  {files[key] && (
                    <button
                      className="icon-button"
                      disabled={busy}
                      aria-label={`Убрать ${key}.csv`}
                      onClick={() => {
                        const next = { ...files };
                        delete next[key];
                        setFiles(next);
                        operationKey.current = null;
                      }}
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
              ))}
              <ErrorMessage error={fileError} />
              <button
                className="button secondary"
                disabled={busy || !resultNames.every((key) => files[key])}
                onClick={() => mutation.mutate('files')}
              >
                Проверить результаты
              </button>
            </details>
          </div>
        </details>
        <div className="analysis-result">
          {run ? (
            <>
              <div
                className={`panel run-progress ${summary ? 'completed' : ''}`}
                aria-live="polite"
              >
                <div className="analysis-actions">
                  <strong>{statusText[run.status]}</strong>
                  <span className="micro">
                    {run.engine_label} · {run.id.slice(0, 8)}
                  </span>
                  {active(run) && (
                    <button
                      className="button secondary"
                      disabled={cancel.isPending}
                      onClick={() => cancel.mutate()}
                    >
                      Отменить
                    </button>
                  )}
                </div>
                <ErrorMessage error={run.error_message} />
                <ErrorMessage error={events.error} />
                <details className="event-details" open={active(run)}>
                  <summary>Журнал этапов · {events.data?.length ?? 0}</summary>
                  <ol className="event-list">
                    {events.data?.map((event) => (
                      <li key={event.id}>
                        <span className="notice-dot" />
                        <span>{event.message}</span>
                      </li>
                    ))}
                  </ol>
                </details>
                {run.status === 'interrupted' && (
                  <p className="micro">
                    Этот запуск не возобновляется автоматически. Нажмите «Запустить анализ» для
                    нового расчёта.
                  </p>
                )}
              </div>
              {summary && <AnalysisDashboard key={run.id} run={run} dataset={dataset} />}
            </>
          ) : (
            <div className="analysis-empty">
              <Play size={30} />
              <h3>Готово к анализу</h3>
              <p>
                Движок рассчитает роли, аномалии и приоритеты. Ход работы и результат появятся
                здесь.
              </p>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
