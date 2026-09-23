import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowDownToLine, Check, FileCheck2, FileUp, Loader2, ShieldCheck, X } from 'lucide-react';
import { api } from '../../api';
import { addFiles, FILE_ROLES, fileSize, type InputFiles } from '../../files';
import { ErrorMessage } from '../../components/ErrorMessage';

export function ImportPanel({ caseId, hasDataset }: { caseId: string; hasDataset: boolean }) {
  const client = useQueryClient();
  const health = useQuery({ queryKey: ['health'], queryFn: api.health });
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<InputFiles>({});
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const maxBytes = health.data?.limits.max_file_bytes ?? 50 * 1024 * 1024;
  const mutation = useMutation({
    mutationFn: () => api.importDataset(caseId, files as Record<string, File>),
    onSuccess: () => {
      setFiles({});
      void client.invalidateQueries({ queryKey: ['case', caseId] });
      void client.invalidateQueries({ queryKey: ['cases'] });
    },
  });
  const accept = (incoming: File[]) => {
    if (mutation.isPending) return;
    try {
      setFiles(addFiles(files, incoming, maxBytes));
      setError(null);
      mutation.reset();
    } catch (value) {
      setError((value as Error).message);
    }
  };
  const complete = FILE_ROLES.every((key) => files[key]);
  return (
    <section className="panel import-panel">
      <div className="panel-heading">
        <span className="square-icon">
          <FileUp size={20} />
        </span>
        <div>
          <h2>{hasDataset ? 'Добавить новый набор' : 'Загрузите исходные данные'}</h2>
          <p>
            {hasDataset
              ? 'Предыдущие наборы останутся в истории кейса.'
              : 'Три файла одного набора. Порядок выбора не важен.'}
          </p>
        </div>
      </div>
      <button
        type="button"
        className={`dropzone ${dragging ? 'dragging' : ''}`}
        disabled={mutation.isPending}
        onClick={() => input.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          accept(Array.from(event.dataTransfer.files));
        }}
      >
        <ArrowDownToLine size={27} />
        <strong>Перетащите parquet-файлы сюда</strong>
        <span>или нажмите, чтобы выбрать · до {Math.round(maxBytes / 1024 / 1024)} МБ каждый</span>
      </button>
      <input
        ref={input}
        type="file"
        className="sr-only"
        aria-label="Выбрать parquet-файлы"
        accept=".parquet"
        multiple
        tabIndex={-1}
        onChange={(event) => {
          accept(Array.from(event.target.files ?? []));
          event.target.value = '';
        }}
      />
      <div className="file-list">
        {FILE_ROLES.map((key) => (
          <div className={`file-row ${files[key] ? 'selected' : ''}`} key={key}>
            <FileCheck2 size={19} />
            <div>
              <strong>{key}.parquet</strong>
              <small>
                {files[key]
                  ? fileSize(files[key]!.size)
                  : {
                      nodes: 'Клиенты и seed-признак',
                      edges: 'Агрегированные связи',
                      transactions: 'Отдельные переводы и даты',
                    }[key]}
              </small>
            </div>
            {files[key] ? (
              <button
                className="icon-button"
                aria-label={`Убрать ${key}.parquet`}
                disabled={mutation.isPending}
                onClick={() => {
                  setFiles({ ...files, [key]: undefined });
                  mutation.reset();
                }}
              >
                <X size={16} />
              </button>
            ) : (
              <span className="file-wait">Ожидается</span>
            )}
          </div>
        ))}
      </div>
      <ErrorMessage error={error || mutation.error} />
      {mutation.isSuccess && (
        <div className="success-message" role="status">
          <Check size={17} /> Набор проверен и сохранён.
        </div>
      )}
      <button
        className="button primary import-submit"
        disabled={!complete || mutation.isPending}
        onClick={() => {
          setError(null);
          mutation.mutate();
        }}
      >
        {mutation.isPending ? <Loader2 className="spin" size={18} /> : <ShieldCheck size={18} />}
        {mutation.isPending ? 'Загружаем и проверяем…' : 'Проверить и сохранить'}
      </button>
      <p className="micro">
        Проверяем структуру, ссылки на клиентов, суммы и количество переводов. Исходные файлы
        сохраняются без изменений.
      </p>
    </section>
  );
}
