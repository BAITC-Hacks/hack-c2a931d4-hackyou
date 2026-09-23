import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Loader2, Plus } from 'lucide-react';
import { api } from '../../api';
import { Modal } from '../../components/Modal';
import { ErrorMessage } from '../../components/ErrorMessage';

export function CreateCase({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const mutation = useMutation({
    mutationFn: () => api.createCase(name.trim(), description.trim()),
    onSuccess: (value) => {
      void client.invalidateQueries({ queryKey: ['cases'] });
      onClose();
      navigate(`/cases/${value.id}`);
    },
  });
  return (
    <Modal title="Новый кейс" onClose={onClose} busy={mutation.isPending}>
      <p className="muted">
        Создайте рабочее пространство. На следующем шаге загрузите данные финансовой сети.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (name.trim()) mutation.mutate();
        }}
      >
        <label className="field">
          Название кейса
          <input
            autoFocus
            required
            maxLength={120}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Например, переводы за июль 2026"
          />
        </label>
        <label className="field">
          Описание <span className="muted">· необязательно</span>
          <textarea
            maxLength={2000}
            rows={3}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Контекст и цель проверки"
          />
        </label>
        <ErrorMessage error={mutation.error} />
        <div className="modal-actions">
          <button
            className="button secondary"
            type="button"
            onClick={onClose}
            disabled={mutation.isPending}
          >
            Отмена
          </button>
          <button className="button primary" disabled={!name.trim() || mutation.isPending}>
            {mutation.isPending ? <Loader2 className="spin" size={17} /> : <Plus size={17} />}{' '}
            Создать кейс
          </button>
        </div>
      </form>
    </Modal>
  );
}
