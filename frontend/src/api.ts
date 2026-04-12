import type {
  ActionSummary,
  ChatAction,
  ChatBootstrap,
  ChatEnvelope,
  DueConcept,
  ReviewLogEntry,
  ReviewStats,
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

export function fetchReviews(limit = 50): Promise<ReviewLogEntry[]> {
  return getJson<ReviewLogEntry[]>(`/api/reviews?limit=${limit}`);
}

export function fetchTopicMap(): Promise<TopicMapNode[]> {
  return getJson<TopicMapNode[]>('/api/topic-map');
}