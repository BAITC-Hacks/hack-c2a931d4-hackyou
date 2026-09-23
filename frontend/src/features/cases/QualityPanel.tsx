import { CircleHelp, Network, ShieldCheck } from 'lucide-react';
import type { Dataset } from '../../api';
import { date, count } from '../../format';
import { fileSize, formatMoney } from '../../files';

export function QualityPanel({ dataset }: { dataset: Dataset }) {
  const quality = dataset.quality;
  return (
    <div className="quality-stack">
      <section className="panel">
        <div className="panel-heading">
          <span className="square-icon green">
            <ShieldCheck size={20} />
          </span>
          <div>
            <h2>Набор прошёл проверку</h2>
            <p>
              Загружен {date(dataset.created_at)} · {quality.checks.length} проверок
            </p>
          </div>
        </div>
        <div className="metrics-grid">
          {[
            ['Клиенты', quality.n_nodes],
            ['Связи', quality.n_edges],
            ['Переводы', quality.n_transactions],
            ['Seed-клиенты', quality.n_seed],
          ].map(([label, value]) => (
            <div key={label}>
              <small>{label}</small>
              <strong>{count(Number(value))}</strong>
            </div>
          ))}
        </div>
        <div className="flow-total">
          <span>Наблюдаемый оборот</span>
          <strong>
            {formatMoney(quality.observed_flow_kzt)} <small>KZT</small>
          </strong>
        </div>
        <div className="period-row">
          <span>Период переводов</span>
          <strong>
            {quality.period_start && quality.period_end
              ? `${date(quality.period_start)} — ${date(quality.period_end)}`
              : 'Нет транзакций'}
          </strong>
        </div>
        <details className="file-details">
          <summary>Исходные файлы и контрольные суммы</summary>
          {dataset.files.map((file) => (
            <div key={file.name}>
              <strong>
                {file.name} · {fileSize(file.size_bytes)}
              </strong>
              <code>{file.sha256}</code>
            </div>
          ))}
        </details>
      </section>
      <section className="panel">
        <div className="section-label">
          КОНТЕКСТ ДАННЫХ <CircleHelp size={17} />
        </div>
        <div className="quality-notices">
          {quality.warnings.map((warning) => (
            <div key={warning.code}>
              <span className="notice-dot" />
              <p>
                {warning.message}
                {warning.count !== null && <strong> Количество: {count(warning.count)}.</strong>}
              </p>
            </div>
          ))}
        </div>
      </section>
      <div className="next-stage">
        <Network size={22} />
        <div>
          <strong>Следующий этап — анализ сети</strong>
          <p>
            Подключение ML-движка ещё не реализовано. Роли, кластеры и приоритеты появятся после
            интеграции.
          </p>
        </div>
      </div>
    </div>
  );
}
