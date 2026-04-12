import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ForecastPage } from './ForecastPage';

function jsonResponse(data: Record<string, unknown> | Array<Record<string, unknown>>) {
  return Promise.resolve({
    ok: true,
    json: async () => data,
  } as Response);
}

function renderForecastPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ForecastPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('ForecastPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders forecast buckets and loads concept detail for the selected bucket', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      switch (String(input)) {
        case '/api/forecast?range=weeks':
          return jsonResponse({
            range_type: 'weeks',
            overdue_count: 2,
            buckets: [
              { label: 'This week', bucket_key: '0', count: 3, avg_mastery: 45 },
              { label: 'Next week', bucket_key: '1', count: 1, avg_mastery: 70 },
            ],
          });
        case '/api/forecast/concepts?range=weeks&bucket=overdue':
          return jsonResponse([
            { id: 7, title: 'Rust Ownership', mastery_level: 45, next_review_at: '2026-04-12 08:00:00', interval_days: 3, review_count: 4 },
          ]);
        case '/api/forecast/concepts?range=weeks&bucket=0':
          return jsonResponse([
            { id: 9, title: 'Borrow Checker', mastery_level: 62, next_review_at: '2026-04-15 08:00:00', interval_days: 5, review_count: 6 },
          ]);
        default:
          throw new Error(`Unexpected fetch: ${String(input)}`);
      }
    });

    const user = userEvent.setup();
    renderForecastPage();

    expect(await screen.findByRole('heading', { name: 'Forecast' })).toBeInTheDocument();
    expect(await screen.findByText('Rust Ownership')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /This week/i }));

    expect(await screen.findByText('Borrow Checker')).toBeInTheDocument();
    expect(screen.queryByText('Rust Ownership')).not.toBeInTheDocument();
  });
});