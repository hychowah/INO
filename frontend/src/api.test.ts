import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fetchBootstrap, sendChat } from './api';

describe('api user header', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('adds the stored user header to JSON requests', async () => {
    window.localStorage.setItem('learning-agent.user-id', 'browser-user-7');
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ history: [], commands: [] }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await fetchBootstrap();

    expect(fetchMock).toHaveBeenCalledWith('/api/chat/bootstrap', {
      headers: {
        'X-Requested-With': 'fetch',
        'X-Learning-User': 'browser-user-7',
      },
    });
  });

  it('omits the user header when no browser user is configured', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ type: 'reply', message: 'ok', pending_action: null }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await sendChat('hello');

    expect(fetchMock).toHaveBeenCalledWith('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Requested-With': 'fetch',
      },
      body: JSON.stringify({ message: 'hello' }),
    });
  });
});