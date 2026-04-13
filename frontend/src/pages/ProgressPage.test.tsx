import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProgressPage } from './ProgressPage';

function jsonResponse(data: Record<string, unknown> | Array<Record<string, unknown>>) {
  return Promise.resolve({
    ok: true,
    json: async () => data,
  } as Response);
}

function renderProgressPage(initialEntry = '/progress') {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <ProgressPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('ProgressPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders reviews by default and switches to forecast without leaving the consolidated page', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      switch (String(input)) {
        case '/api/reviews?limit=50':
          return jsonResponse([
            {
              id: 11,
              concept_id: 7,
              concept_title: 'Rust Ownership',
              question_asked: 'What does ownership prevent?',
              user_response: 'Data races and double free bugs.',
              quality: 4,
              llm_assessment: 'Strong answer with the right tradeoff focus.',
              reviewed_at: '2026-04-12 08:30:00',
            },
          ]);
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
        default:
          throw new Error(`Unexpected fetch: ${String(input)}`);
      }
    });

    const user = userEvent.setup();
    renderProgressPage();

    expect(await screen.findByRole('heading', { name: 'Review performance' })).toBeInTheDocument();
    expect(await screen.findByText('Rust Ownership')).toBeInTheDocument();
    expect(await screen.findByText('What does ownership prevent?')).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Forecast' }));

    expect(await screen.findByRole('heading', { name: 'Bucket Detail' })).toBeInTheDocument();
    expect(await screen.findAllByText('Rust Ownership')).not.toHaveLength(0);
  });
});