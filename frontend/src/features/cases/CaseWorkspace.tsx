import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, Check, Layers3, Loader2, ShieldCheck } from 'lucide-react';
import { api } from '../../api';
import { date } from '../../format';
import { ErrorMessage } from '../../components/ErrorMessage';
import { ImportPanel } from './ImportPanel';
import { QualityPanel } from './QualityPanel';
import { Status } from './Status';

export function CaseWorkspace() {
  const { caseId = '' } = useParams();
  const query = useQuery({
    queryKey: ['case', caseId],
    queryFn: () => api.getCase(caseId),
    retry: false,
  });
  const [selected, setSelected] = useState('');
  const item = query.data;
  const dataset = item?.datasets.find((value) => value.id === selected) ?? item?.latest_dataset;
  return (
    <>
      <Link to="/" className="back-link">
        <ArrowLeft size={16} /> Все кейсы
      </Link>
      {query.isPending && (
        <div className="loading">
          <Loader2 className="spin" /> Загружаем кейс…
        </div>
      )}
      <ErrorMessage error={query.error} />
      {item && (
        <>
          <div className="page-heading case-heading">
            <div>
              <div className="eyebrow">КЕЙС · {item.id.slice(0, 8).toUpperCase()}</div>
              <h1>{item.name}</h1>
              <p className="muted">
                {item.description || 'Исходные данные и результаты проверки финансовой сети.'}
              </p>
            </div>
            <Status item={item} />
          </div>
          <div className="case-tabs">
            <span className="active">
              <Layers3 size={16} /> Данные кейса
            </span>
            <span className="tab-note">Создан {date(item.created_at)}</span>
          </div>
          {item.datasets.length > 1 && (
            <label className="dataset-select">
              Сохранённый набор
              <select value={dataset?.id} onChange={(event) => setSelected(event.target.value)}>
                {item.datasets.map((value, index) => (
                  <option key={value.id} value={value.id}>
                    Набор {item.datasets.length - index} · {date(value.created_at)} ·{' '}
                    {value.id.slice(0, 8)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="case-grid">
            <ImportPanel key={caseId} caseId={caseId} hasDataset={Boolean(item.latest_dataset)} />
            {dataset ? (
              <QualityPanel dataset={dataset} />
            ) : (
              <div className="preflight-panel">
                <div className="eyebrow">ПЕРЕД НАЧАЛОМ</div>
                <h2>
                  Один кейс.
                  <br />
                  Целостная сеть.
                </h2>
                <p>Загрузите полный набор файлов, относящийся к одному периоду и одной выгрузке.</p>
                <div className="preflight-item">
                  <Check size={17} />
                  <span>Все участники связей должны присутствовать в nodes.</span>
                </div>
                <div className="preflight-item">
                  <Check size={17} />
                  <span>Суммы и число транзакций должны совпадать с агрегированными рёбрами.</span>
                </div>
                <div className="preflight-item">
                  <Check size={17} />
                  <span>Клиенты без переводов тоже сохраняются.</span>
                </div>
                <div className="preflight-footer">
                  <ShieldCheck size={18} /> Файлы остаются на этом компьютере.
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
