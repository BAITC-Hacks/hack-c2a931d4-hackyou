export const date = (value: string) =>
  new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', year: 'numeric' }).format(
    new Date(value),
  );
export const count = (value: number) => new Intl.NumberFormat('ru-RU').format(value);
