import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ActivityPage } from './ActivityPage';

function jsonResponse(data: Record<string, unknown> | Array<Record<string, unknown>>) {
  return Promise.resolve({
    ok: true,
    json: async () => data,
  } as Response);
}

function renderActivityPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <ActivityPage />
    </QueryClientProvider>
  );
}

describe('ActivityPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders action entries and expands row details', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      switch (String(input)) {
        case '/api/actions/filters':
          return jsonResponse({ actions: ['assess', 'add_concept'], sources: ['api', 'discord'] });
        case '/api/actions?time=all&page=1&per_page=20':
          return jsonResponse({
            items: [
              {
                id: 11,
                action: 'assess',
                params: JSON.stringify({ concept_id: 7, quality: 4 }),
                result_type: 'success',
                result: JSON.stringify({ message: 'ok' }),
                source: 'api',
                created_at: '2026-04-12 09:00:00',
              },
            ],
            total: 1,
            page: 1,
            per_page: 20,
          });
        default:
          throw new Error(`Unexpected fetch: ${String(input)}`);
      }
    });

    const user = userEvent.setup();
    renderActivityPage();

    expect(await screen.findByRole('heading', { name: 'Activity Log' })).toBeInTheDocument();
    expect(await screen.findByText('concept_id: 7 · quality: 4')).toBeInTheDocument();

    await user.click(screen.getByText('concept_id: 7 · quality: 4'));

    expect(await screen.findByText(/"concept_id": 7/)).toBeInTheDocument();
    expect(await screen.findByText(/"message": "ok"/)).toBeInTheDocument();
  });
});