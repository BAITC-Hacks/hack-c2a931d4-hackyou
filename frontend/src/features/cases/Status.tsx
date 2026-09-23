import type { Case } from '../../api';

export function Status({ item }: { item: Case }) {
  return (
    <span className={`badge ${item.status === 'data_ready' ? 'ready' : 'draft'}`}>
      <i />
      {item.status === 'data_ready' ? 'Данные проверены' : 'Ожидает данные'}
    </span>
  );
}
