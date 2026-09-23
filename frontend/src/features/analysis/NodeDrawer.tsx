import { useEffect, useId, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ArrowDownLeft, ArrowUpRight, X } from 'lucide-react';
import { api } from '../../api';
import { ErrorMessage } from '../../components/ErrorMessage';
import { formatMoney } from '../../files';
import { count } from '../../format';
import { evidenceSources, evidenceText, roles, score } from './presentation';

const signals: Record<string, string> = {
  seed_convergence: 'Сходимость исходных узлов',
  structural_importance: 'Структурная значимость',
  flow_significance: 'Значимость потока',
  role_strength: 'Выраженность роли',
  anomaly_score: 'Аномальность',
  cluster_bridge: 'Связь между сообществами',
};

function ScoreBars({
  values,
  labels,
}: {
  values: Record<string, number>;
  labels: Record<string, string>;
}) {
  return (
    <div className="profile-bars">
      {Object.entries(values)
        .sort((a, b) => b[1] - a[1])
        .map(([key, value]) => (
          <div key={key}>
            <span>{labels[key] ?? key}</span>
            <span className="profile-track">
              <i
                style={{
                  width: `${Math.max(0, Math.min(1, value)) * 100}%`,
                  background: roles[key]?.color,
                }}
              />
            </span>
            <strong>{score(value)}</strong>
          </div>
        ))}
    </div>
  );
}

export function NodeDrawer({
  analysisId,
  gid,
  onClose,
  onExplore,
}: {
  analysisId: string;
  gid: string;
  onClose: () => void;
  onExplore?: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    ref.current?.showModal();
    return () => opener?.focus({ preventScroll: true });
  }, []);
  return (
    <dialog
      ref={ref}
      className="node-drawer"
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header className="drawer-heading">
        <div>
          <div className="eyebrow">КАРТОЧКА УЧАСТНИКА</div>
          <h2 id={titleId}>GID {gid}</h2>
          <p className="micro">Снимок анализа · {analysisId.slice(0, 8)}</p>
        </div>
        <button className="icon-button" onClick={onClose} aria-label="Закрыть карточку">
          <X size={21} />
        </button>
      </header>
      {onExplore && (
        <button className="button primary drawer-explore" onClick={onExplore}>
          Исследовать связи <ArrowUpRight size={16} />
        </button>
      )}
      <NodeProfile analysisId={analysisId} gid={gid} />
    </dialog>
  );
}

export function NodeProfile({ analysisId, gid }: { analysisId: string; gid: string }) {
  const query = useQuery({
    queryKey: ['analysis-node', analysisId, gid],
    queryFn: () => api.analysisNode(analysisId, gid),
  });
  const node = query.data?.node;
  const profile = query.data?.profile;
  return (
    <div className="drawer-body">
      <ErrorMessage error={query.error} />
      {query.isPending && <p role="status">Загружаем профиль участника…</p>}
      {node && (
        <>
          <div className="profile-summary">
            <div>
              <span className="role-pill">
                <i style={{ background: roles[node.role]?.color }} />
                {roles[node.role]?.label ?? node.role}
              </span>
              <p>{roles[node.role]?.description}</p>
              <span className="micro">
                Сообщество #{node.cluster_id}
                {profile &&
                  ` · Глубина ${profile.depth}${profile.is_seed ? ' · Исходный узел (seed)' : ''}`}
              </span>
            </div>
            <div className="profile-priority">
              <span>Приоритет</span>
              <strong>{score(node.priority_score)}</strong>
              <small>из 1</small>
            </div>
          </div>
          <div className="profile-explanation">
            <strong>Почему в выборке</strong>
            <p>{evidenceText(node.evidence)}</p>
          </div>
          {!profile && (
            <p className="profile-notice">
              В импортированных CSV есть только краткое основание и итоговые оценки. Подробный
              профиль доступен для анализа, выполненного движком.
            </p>
          )}
        </>
      )}
      {profile && (
        <>
          {(profile.role_ambiguity || profile.truncated_by_depth) && (
            <div className="profile-notice">
              {profile.role_ambiguity && (
                <p>
                  <strong>Роль неоднозначна.</strong>
                  {profile.secondary_role
                    ? ` Альтернативная гипотеза: ${roles[profile.secondary_role]?.label ?? profile.secondary_role}.`
                    : ' Сравните оценки ролевых гипотез ниже.'}
                </p>
              )}
              {profile.truncated_by_depth && (
                <p>
                  <strong>Граница выгрузки.</strong> Продолжение потока может находиться вне
                  наблюдаемой сети.
                </p>
              )}
            </div>
          )}
          <div className="flow-cards">
            <div>
              <span>
                <ArrowDownLeft size={18} /> Входящий поток
              </span>
              <strong>
                {formatMoney(profile.in_kzt)} <small>₸</small>
              </strong>
              <p>
                {count(profile.in_tx)} переводов · {count(profile.in_degree)} связей
              </p>
            </div>
            <div>
              <span>
                <ArrowUpRight size={18} /> Исходящий поток
              </span>
              <strong>
                {formatMoney(profile.out_kzt)} <small>₸</small>
              </strong>
              <p>
                {count(profile.out_tx)} переводов · {count(profile.out_degree)} связей
              </p>
            </div>
          </div>
          <section className="profile-section">
            <h3>Сравнение ролевых гипотез</h3>
            <p className="micro">
              Выраженность каждой роли по оценке движка. Значения не складываются в 100%.
            </p>
            <ScoreBars
              values={profile.role_scores}
              labels={Object.fromEntries(
                Object.entries(roles).map(([key, role]) => [key, role.label]),
              )}
            />
          </section>
          <section className="profile-section">
            <h3>Сигналы для приоритета</h3>
            <p className="micro">
              Нормированные значения сигналов, а не их доли в итоговом приоритете.
            </p>
            <ScoreBars values={profile.priority_components} labels={signals} />
          </section>
          <section className="profile-section">
            <h3>Основания и ограничения</h3>
            <p className="micro">
              Наблюдаемость по оценке движка: {score(profile.observability_score)} из 1.
            </p>
            {(
              [
                ['observation', 'Наблюдения'],
                ['inference', 'Интерпретации движка'],
                ['limitation', 'Ограничения'],
              ] as const
            ).map(([kind, label]) => {
              const evidence = profile.evidence.filter((item) => item.kind === kind);
              return (
                evidence.length > 0 && (
                  <details
                    className={`evidence-group ${kind}`}
                    key={kind}
                    open={kind === 'limitation'}
                  >
                    <summary>
                      {label} <span>{evidence.length}</span>
                    </summary>
                    <ul>
                      {evidence.map((item, index) => (
                        <li key={index}>
                          <p>{item.text}</p>
                          <small>Источник: {evidenceSources[item.source] ?? item.source}</small>
                        </li>
                      ))}
                    </ul>
                  </details>
                )
              );
            })}
          </section>
        </>
      )}
    </div>
  );
}
