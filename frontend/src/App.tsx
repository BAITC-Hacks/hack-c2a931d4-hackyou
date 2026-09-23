import { useQuery } from '@tanstack/react-query';

export function App() {
  const health = useQuery({
    queryKey: ['health'],
    queryFn: async () => {
      const response = await fetch('/api/v1/health');
      if (!response.ok) throw new Error('Backend unavailable');
      return response.json() as Promise<{ status: string }>;
    },
  });

  return <main className="foundation">
    <p>TRACEGRAPH / LOCAL WORKSPACE</p>
    <h1>Финансовая сеть.<br />Объяснимые связи.</h1>
    <p>Подготовка рабочего места аналитика.</p>
    <span>{health.isSuccess ? 'Backend подключён' : health.isError ? 'Backend недоступен' : 'Подключение…'}</span>
  </main>;
}
