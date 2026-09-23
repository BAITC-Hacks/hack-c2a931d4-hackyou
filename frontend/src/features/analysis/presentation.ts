export const roles: Record<string, { label: string; color: string; description: string }> = {
  consolidator: {
    label: 'Консолидатор',
    color: '#24776c',
    description: 'Собирает потоки от нескольких участников.',
  },
  transit: {
    label: 'Транзит',
    color: '#6399c0',
    description: 'Передаёт поступившие средства дальше по сети.',
  },
  distributor: {
    label: 'Распределитель',
    color: '#d8a348',
    description: 'Распределяет средства между получателями.',
  },
  terminal: {
    label: 'Терминальный',
    color: '#cc775d',
    description: 'Конечная точка потока в наблюдаемой сети.',
  },
  coordinator: {
    label: 'Координатор',
    color: '#8b7aac',
    description: 'Связывает значимые части сети по оценке движка.',
  },
  peripheral: {
    label: 'Периферия',
    color: '#a7b6a3',
    description: 'Слабо выраженная структурная роль в этой выгрузке.',
  },
};

export const score = (value: number) => value.toLocaleString('ru-RU', { maximumFractionDigits: 3 });
export const percent = (part: number, total: number) =>
  `${(total ? (part / total) * 100 : 0).toLocaleString('ru-RU', { maximumFractionDigits: 1 })}%`;
export const bucketLabel = (index: number) => `${score(index / 5)}–${score((index + 1) / 5)}`;

export function evidenceText(text: string): string {
  return text
    .replace(/^(\w+):/, (match, key: string) => (roles[key] ? `${roles[key].label}:` : match))
    .replace(/\bKZT\b/g, '₸')
    .replace(/\bseeds=/g, 'связанных исходных узлов: ')
    .replace(/\bconfidence=/g, 'уверенность движка: ');
}

export const evidenceSources: Record<string, string> = {
  deterministic_features: 'Структура и объёмы переводов',
  temporal_features: 'Даты и последовательности переводов',
  deterministic_role_engine: 'Правила ролевой модели',
  seed_lineage_engine: 'Связи с исходными узлами',
  autoencoder_reconstruction_error: 'Модель аномалий Autoencoder',
  counterfactual_analysis: 'Контрфактический анализ',
};

// Two arcs also cover the 100% case, which a single SVG arc cannot draw.
export function ringSegment(start: number, fraction: number): string {
  const point = (turn: number, radius: number) => {
    const angle = turn * 2 * Math.PI - Math.PI / 2;
    return `${120 + Math.cos(angle) * radius},${120 + Math.sin(angle) * radius}`;
  };
  const middle = start + fraction / 2;
  const end = start + fraction;
  return `M${point(start, 104)} A104,104 0 0 1 ${point(middle, 104)} A104,104 0 0 1 ${point(end, 104)} L${point(end, 77)} A77,77 0 0 0 ${point(middle, 77)} A77,77 0 0 0 ${point(start, 77)} Z`;
}
