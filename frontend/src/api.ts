import type {
  ActionSummary,
  ActionFilterOptions,
  ActionLogResponse,
  ChatAction,
  ChatBootstrap,
  ChatEnvelope,
  ConceptListResponse,
  ConceptListSortField,
  ConceptListStatus,
  ForecastConcept,
  ForecastSummary,
  GraphResponse,
  ConceptDetail,
  ConceptRelation,
  DueConcept,
  ReviewLogEntry,
  ReviewStats,
  TopicDetail,
  TopicSummary,
  TopicMapNode,
} from './types';

async function parseJson<T>(response: Response): Promise<T> {
  const data = (await response.json()) as T;
  if (!response.ok) {
    const message = (data as { detail?: string; message?: string }).detail ||
      (data as { detail?: string; message?: string }).message ||
      'Request failed';
    throw new Error(message);
  }
  return data;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    headers: {
      'X-Requested-With': 'fetch'
    }
  });
  return parseJson<T>(response);
}

export async function fetchBootstrap(): Promise<ChatBootstrap> {
  return getJson<ChatBootstrap>('/api/chat/bootstrap');
}

async function postJson<T>(path: string, payload: object): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'fetch'
    },
    body: JSON.stringify(payload)
  });
  return parseJson<T>(response);
}

export function sendChat(message: string): Promise<ChatEnvelope> {
  return postJson<ChatEnvelope>('/api/chat', { message });
}

export function confirmPending(action_data: Record<string, unknown>): Promise<ChatEnvelope> {
  return postJson<ChatEnvelope>('/api/chat/confirm', { action_data });
}

export function declinePending(action_data: Record<string, unknown>): Promise<ChatEnvelope> {
  return postJson<ChatEnvelope>('/api/chat/decline', { action_data });
}

export function runChatAction(action: ChatAction): Promise<ChatEnvelope> {
  return postJson<ChatEnvelope>('/api/chat/action', { action });
}

export function fetchReviewStats(): Promise<ReviewStats> {
  return getJson<ReviewStats>('/api/stats');
}

export function fetchDueConcepts(limit = 10): Promise<DueConcept[]> {
  return getJson<DueConcept[]>(`/api/due?limit=${limit}`);
}

export function fetchActionSummary(days = 7): Promise<ActionSummary> {
  return getJson<ActionSummary>(`/api/action-summary?days=${days}`);
}

export function fetchActionLog(params: {
  action?: string;
  source?: string;
  search?: string;
  time?: string;
  page?: number;
  perPage?: number;
}): Promise<ActionLogResponse> {
  const query = new URLSearchParams();
  if (params.action) query.set('action', params.action);
  if (params.source) query.set('source', params.source);
  if (params.search) query.set('search', params.search);
  if (params.time) query.set('time', params.time);
  if (params.page) query.set('page', String(params.page));
  if (params.perPage) query.set('per_page', String(params.perPage));
  const suffix = query.toString();
  return getJson<ActionLogResponse>(`/api/actions${suffix ? `?${suffix}` : ''}`);
}

export function fetchActionFilters(): Promise<ActionFilterOptions> {
  return getJson<ActionFilterOptions>('/api/actions/filters');
}

export function fetchForecast(range: 'days' | 'weeks' | 'months'): Promise<ForecastSummary> {
  return getJson<ForecastSummary>(`/api/forecast?range=${range}`);
}

export function fetchForecastConcepts(range: 'days' | 'weeks' | 'months', bucket: string): Promise<ForecastConcept[]> {
  return getJson<ForecastConcept[]>(`/api/forecast/concepts?range=${range}&bucket=${encodeURIComponent(bucket)}`);
}

export function fetchGraph(params: {
  topicId?: number;
  minMastery?: number;
  maxMastery?: number;
  maxNodes?: number;
}): Promise<GraphResponse> {
  const query = new URLSearchParams();
  if (params.topicId) query.set('topic_id', String(params.topicId));
  if (typeof params.minMastery === 'number') query.set('min_mastery', String(params.minMastery));
  if (typeof params.maxMastery === 'number') query.set('max_mastery', String(params.maxMastery));
  query.set('max_nodes', String(params.maxNodes ?? 500));
  return getJson<GraphResponse>(`/api/graph?${query.toString()}`);
}

export function fetchReviews(limit = 50): Promise<ReviewLogEntry[]> {
  return getJson<ReviewLogEntry[]>(`/api/reviews?limit=${limit}`);
}

export function fetchTopicMap(): Promise<TopicMapNode[]> {
  return getJson<TopicMapNode[]>('/api/topic-map');
}

export function fetchTopicsFlat(): Promise<TopicSummary[]> {
  return getJson<TopicSummary[]>('/api/topics/flat');
}

export function fetchConcepts(params: {
  search?: string;
  topicId?: number;
  status?: ConceptListStatus;
  sort?: ConceptListSortField;
  order?: 'asc' | 'desc';
  page?: number;
  perPage?: number;
}): Promise<ConceptListResponse> {
  const query = new URLSearchParams();
  if (params.search) query.set('search', params.search);
  if (params.topicId) query.set('topic_id', String(params.topicId));
  if (params.status && params.status !== 'all') query.set('status', params.status);
  if (params.sort) query.set('sort', params.sort);
  if (params.order) query.set('order', params.order);
  if (params.page) query.set('page', String(params.page));
  if (params.perPage) query.set('per_page', String(params.perPage));
  const suffix = query.toString();
  return getJson<ConceptListResponse>(`/api/concepts${suffix ? `?${suffix}` : ''}`);
}

export async function deleteConcept(conceptId: number): Promise<{ message: string }> {
  const response = await fetch(`/api/concepts/${conceptId}`, {
    method: 'DELETE',
    headers: {
      'X-Requested-With': 'fetch',
    },
  });
  return parseJson<{ message: string }>(response);
}

export function fetchTopicDetail(topicId: number): Promise<TopicDetail> {
  return getJson<TopicDetail>(`/api/topics/${topicId}`);
}

export function fetchConceptDetail(conceptId: number): Promise<ConceptDetail> {
  return getJson<ConceptDetail>(`/api/concepts/${conceptId}`);
}

export function fetchConceptRelations(conceptId: number): Promise<ConceptRelation[]> {
  return getJson<ConceptRelation[]>(`/api/concepts/${conceptId}/relations`);
}