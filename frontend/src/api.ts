export interface QualityNotice {
  code: string;
  message: string;
  count: number | null;
}
export interface DatasetQuality {
  status: 'valid';
  n_nodes: number;
  n_edges: number;
  n_transactions: number;
  n_seed: number;
  n_isolated: number;
  n_boundary: number;
  observed_flow_kzt: string;
  period_start: string | null;
  period_end: string | null;
  checks: string[];
  warnings: QualityNotice[];
}
export interface Dataset {
  id: string;
  case_id: string;
  created_at: string;
  files: { name: string; size_bytes: number; sha256: string }[];
  quality: DatasetQuality;
}
export interface Case {
  id: string;
  name: string;
  description: string;
  created_at: string;
  status: 'draft' | 'data_ready';
  dataset_count: number;
  latest_dataset: Dataset | null;
}
export interface CaseDetail extends Case {
  datasets: Dataset[];
}
export interface CasePage {
  items: Case[];
  total: number;
  limit: number;
  offset: number;
}
export interface Health {
  status: string;
  engine: string;
  limits: { max_file_bytes: number };
  capabilities: { analysis: boolean; result_import: boolean };
}

export type AnalysisStatus =
  'queued' | 'running' | 'validating' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted';
export interface Analysis {
  id: string;
  case_id: string;
  dataset_id: string;
  source: 'command' | 'uploaded_csv';
  engine_label: string;
  status: AnalysisStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  files: Dataset['files'];
  summary: {
    n_nodes: number;
    n_clusters: number;
    n_ranked: number;
    role_counts: Record<string, number>;
    top_nodes: { rank: number; gid: string; role: string; priority_score: number; why: string }[];
    warnings: string[];
    model_backend: string | null;
    fallback_reason: string | null;
    elapsed_seconds: number | null;
    engine_analysis_id: string | null;
  } | null;
}
export interface AnalysisEvent {
  id: number;
  status: AnalysisStatus;
  message: string;
  created_at: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch('/api/v1' + path, options);
  } catch {
    throw new ApiError('Нет соединения с backend. Проверьте, что приложение запущено.', 0);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const details = body?.error?.issues
      ?.map((item: { field: string; message: string }) => `${item.field}: ${item.message}`)
      .join('; ');
    throw new ApiError(
      [body?.error?.message || 'Не удалось выполнить запрос.', details].filter(Boolean).join(' '),
      response.status,
    );
  }
  return body as T;
}

export const api = {
  health: () => request<Health>('/health'),
  listAnalyses: (datasetId: string, offset: number) =>
    request<{ items: Analysis[]; total: number }>(
      `/datasets/${datasetId}/analyses?limit=10&offset=${offset}`,
    ),
  getAnalysis: (id: string) => request<Analysis>(`/analyses/${id}`),
  analysisEvents: (id: string) => request<AnalysisEvent[]>(`/analyses/${id}/events`),
  startAnalysis: (datasetId: string, requestKey: string) =>
    request<Analysis>(`/datasets/${datasetId}/analyses`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_key: requestKey }),
    }),
  cancelAnalysis: (id: string) => request<Analysis>(`/analyses/${id}/cancel`, { method: 'POST' }),
  importResults: (datasetId: string, requestKey: string, files: Record<string, File>) => {
    const body = new FormData();
    body.append('request_key', requestKey);
    Object.entries(files).forEach(([key, file]) => body.append(key, file));
    return request<Analysis>(`/datasets/${datasetId}/results`, { method: 'POST', body });
  },
  listCases: (search: string, offset: number) =>
    request<CasePage>(`/cases?search=${encodeURIComponent(search)}&offset=${offset}&limit=12`),
  getCase: (id: string) => request<CaseDetail>(`/cases/${encodeURIComponent(id)}`),
  createCase: (name: string, description: string) =>
    request<Case>('/cases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description }),
    }),
  importDataset: (caseId: string, files: Record<string, File>) => {
    const body = new FormData();
    Object.entries(files).forEach(([key, file]) => body.append(key, file));
    return request<Dataset>(`/cases/${encodeURIComponent(caseId)}/datasets`, {
      method: 'POST',
      body,
    });
  },
};
