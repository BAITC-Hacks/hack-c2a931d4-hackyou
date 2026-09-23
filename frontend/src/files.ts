export const FILE_ROLES = ['nodes', 'edges', 'transactions'] as const;
export type FileRole = (typeof FILE_ROLES)[number];
export type InputFiles = Partial<Record<FileRole, File>>;

export function addFiles(current: InputFiles, incoming: File[], maxBytes: number): InputFiles {
  const next = { ...current };
  const seen = new Set<string>();
  for (const file of incoming) {
    const role = FILE_ROLES.find((key) => file.name.toLowerCase() === `${key}.parquet`);
    if (!role)
      throw new Error(
        `Неизвестный файл «${file.name}». Нужны nodes.parquet, edges.parquet и transactions.parquet.`,
      );
    if (seen.has(role)) throw new Error(`Файл ${role}.parquet выбран дважды.`);
    if (file.size === 0) throw new Error(`Файл ${file.name} пуст.`);
    if (file.size > maxBytes)
      throw new Error(
        `Файл ${file.name} превышает лимит ${Math.round(maxBytes / 1024 / 1024)} МБ.`,
      );
    seen.add(role);
    next[role] = file;
  }
  return next;
}

export function formatMoney(value: string): string {
  const [whole, fraction] = value.split('.');
  return (
    new Intl.NumberFormat('ru-RU').format(BigInt(whole)) +
    (fraction && Number(fraction) !== 0 ? ',' + fraction : '')
  );
}

export function fileSize(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} КБ`
    : `${(bytes / 1024 / 1024).toFixed(1)} МБ`;
}
