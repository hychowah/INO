import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DashboardPage } from './DashboardPage';

type FetchJson = Record<string, unknown> | Array<Record<string, unknown>>;

function jsonResponse(data: FetchJson) {
  return Promise.resolve({
    ok: true,
    json: async () => data,
  } as Response);
}

function renderDashboardPage() {
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
        <DashboardPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders dashboard data from the API bundle', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      switch (String(input)) {
        case '/api/stats':
          return jsonResponse({
            total_concepts: 12,
            total_reviews: 30,
            due_now: 4,
            avg_mastery: 61.5,
            reviews_last_7d: 9,
          });
        case '/api/due?limit=10':
          return jsonResponse([
            { id: 7, title: 'Rust Ownership', mastery_level: 45, next_review_at: '2026-04-12 08:00:00' },
          ]);
        case '/api/action-summary?days=7':
          return jsonResponse({
            days: 7,
            total: 6,
            today_total: 2,
            by_action: { assess: 3, add_concept: 1 },
            today_by_action: { assess: 2 },
          });
        case '/api/topic-map':
          return jsonResponse([
            {
              id: 1,
              title: 'Systems',
              description: null,
              concept_count: 3,
              avg_mastery: 50,
              due_count: 1,
              parent_ids: [],
              child_ids: [2],
            },
            {
              id: 2,
              title: 'Operating Systems',
              description: null,
              concept_count: 2,
              avg_mastery: 45,
              due_count: 1,
              parent_ids: [1],
              child_ids: [],
            },
          ]);
        default:
          throw new Error(`Unexpected fetch: ${String(input)}`);
      }
    });

    renderDashboardPage();

    expect(await screen.findByRole('heading', { name: 'Dashboard', level: 2 })).toBeInTheDocument();
    expect(await screen.findByText('12')).toBeInTheDocument();
    expect(await screen.findByText('Rust Ownership')).toBeInTheDocument();
    expect(
      await screen.findByText((content) => content.includes('Today:') && content.includes('2 reviews'))
    ).toBeInTheDocument();
    expect(await screen.findByText('Systems')).toBeInTheDocument();
    expect(await screen.findByText('Operating Systems')).toBeInTheDocument();
  });
});