import type { ChatAction, ChatBootstrap, ChatEnvelope } from './types';

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

export async function fetchBootstrap(): Promise<ChatBootstrap> {
  const response = await fetch('/api/chat/bootstrap');
  return parseJson<ChatBootstrap>(response);
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