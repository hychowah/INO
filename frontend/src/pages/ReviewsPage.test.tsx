import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ReviewsPage } from './ReviewsPage';

type FetchJson = Record<string, unknown> | Array<Record<string, unknown>>;

function jsonResponse(data: FetchJson) {
  return Promise.resolve({
    ok: true,
    json: async () => data,
  } as Response);
}

function renderReviewsPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <ReviewsPage />
    </QueryClientProvider>
  );
}

describe('ReviewsPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders the recent review log from the API', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      if (String(input) === '/api/reviews?limit=50') {
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
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });

    renderReviewsPage();

    expect(await screen.findByRole('heading', { name: 'Review Log', level: 2 })).toBeInTheDocument();
    expect(await screen.findByText('Rust Ownership')).toBeInTheDocument();
    expect(await screen.findByText('What does ownership prevent?')).toBeInTheDocument();
    expect(await screen.findByText('Data races and double free bugs.')).toBeInTheDocument();
    expect(await screen.findByText(/4\s*\/\s*5/)).toBeInTheDocument();
    expect(await screen.findByText('Strong answer with the right tradeoff focus.')).toBeInTheDocument();
  });
});