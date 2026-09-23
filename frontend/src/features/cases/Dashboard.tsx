import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  ArrowUpRight,
  FolderOpen,
  Layers3,
  Loader2,
  Network,
  Plus,
  Search,
  ShieldCheck,
} from 'lucide-react';
import { api } from '../../api';
import { date, count } from '../../format';
import { ErrorMessage } from '../../components/ErrorMessage';
import { Status } from './Status';

export function Dashboard({ onCreate }: { onCreate: () => void }) {
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search);
      setOffset(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);
  const cases = useQuery({
    queryKey: ['cases', query, offset],
    queryFn: () => api.listCases(query, offset),
  });
  return (
    <>
      <div className="page-heading">
        <div>
          <div className="eyebrow">РАБОЧЕЕ ПРОСТРАНСТВО</div>
          <h1>Ваши кейсы</h1>
          <p className="muted">От транзакций — к структуре финансовой сети.</p>
        </div>
        <button className="button primary" onClick={onCreate}>
          <Plus size={18} /> Новый кейс
        </button>
      </div>
      <div className="intro-grid">
        <section className="intro-card">
          <div className="eyebrow">НАЧНИТЕ С ДАННЫХ</div>
          <h2>
            Каждая связь
            <br />
            имеет значение.
          </h2>
          <p>
            Объедините клиентов и переводы в одном кейсе.
            <br />
            Сохраните данные для дальнейшего анализа.
          </p>
          <button className="text-button" onClick={onCreate}>
            Создать первый набор <ArrowUpRight size={18} />
          </button>
          <div className="intro-mark" aria-hidden="true">
            <Network size={118} strokeWidth={0.8} />
          </div>
        </section>
        <section className="workflow-card">
          <div className="section-label">
            КАК УСТРОЕН КЕЙС <Layers3 size={17} />
          </div>
          {[
            ['01', 'Загрузите три файла', 'Клиенты, связи и транзакции в Parquet.'],
            ['02', 'Проверьте качество', 'Структура, суммы и полнота ссылок.'],
            ['03', 'Вернитесь к результату', 'Наборы сохраняются на этом компьютере.'],
          ].map(([number, title, text]) => (
            <div className="workflow-step" key={number}>
              <span>{number}</span>
              <div>
                <strong>{title}</strong>
                <p>{text}</p>
              </div>
            </div>
          ))}
        </section>
      </div>
      <section className="case-list">
        <div className="list-toolbar">
          <div className="section-title">
            История кейсов <span className="count-pill">{cases.data?.total ?? '—'}</span>
          </div>
          <label className="search">
            <Search size={17} />
            <input
              aria-label="Найти кейс"
              placeholder="Найти по названию"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
        </div>
        <ErrorMessage error={cases.error} />
        {cases.isError && (
          <button className="button secondary retry" onClick={() => void cases.refetch()}>
            Повторить загрузку
          </button>
        )}
        {cases.isPending ? (
          <div className="loading" role="status">
            <Loader2 className="spin" /> Загружаем кейсы…
          </div>
        ) : cases.data?.items.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Кейс</th>
                  <th>Статус</th>
                  <th>Клиенты / переводы</th>
                  <th>Создан</th>
                  <th>
                    <span className="sr-only">Открыть</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {cases.data.items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <Link className="case-link" to={`/cases/${item.id}`}>
                        <span className="case-icon">
                          <FolderOpen size={18} />
                        </span>
                        <div>
                          <strong>{item.name}</strong>
                          <small>
                            {item.latest_dataset
                              ? `${item.dataset_count} наб. · ${item.latest_dataset.quality.period_start ? date(item.latest_dataset.quality.period_start) : 'Период не задан'}`
                              : 'Добавьте исходные файлы'}
                          </small>
                        </div>
                      </Link>
                    </td>
                    <td>
                      <Status item={item} />
                    </td>
                    <td className="mono">
                      {item.latest_dataset
                        ? `${count(item.latest_dataset.quality.n_nodes)} / ${count(item.latest_dataset.quality.n_transactions)}`
                        : '—'}
                    </td>
                    <td className="table-date">{date(item.created_at)}</td>
                    <td>
                      <Link
                        className="icon-button"
                        aria-label={`Открыть ${item.name}`}
                        to={`/cases/${item.id}`}
                      >
                        <ArrowUpRight size={18} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          cases.isSuccess && (
            <div className="empty-state">
              <div className="empty-icon">
                <FolderOpen size={28} />
              </div>
              <h3>{query ? 'Кейсы не найдены' : 'Здесь начинается расследование'}</h3>
              <p>
                {query
                  ? 'Попробуйте другое название.'
                  : 'Создайте кейс и загрузите три parquet-файла. Мы проверим данные и сохраним их для работы.'}
              </p>
              {!query && (
                <button className="button secondary" onClick={onCreate}>
                  <Plus size={17} /> Создать кейс
                </button>
              )}
            </div>
          )
        )}
        {cases.data && cases.data.total > 12 && (
          <div className="pagination">
            <span>
              {offset + 1}–{Math.min(offset + 12, cases.data.total)} из {cases.data.total}
            </span>
            <button
              className="button secondary"
              disabled={offset === 0}
              onClick={() => setOffset(offset - 12)}
            >
              Назад
            </button>
            <button
              className="button secondary"
              disabled={offset + 12 >= cases.data.total}
              onClick={() => setOffset(offset + 12)}
            >
              Далее
            </button>
          </div>
        )}
      </section>
      <div className="local-note">
        <ShieldCheck size={16} /> Данные и история хранятся локально на этом компьютере.
      </div>
    </>
  );
}
