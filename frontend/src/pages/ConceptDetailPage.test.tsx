import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConceptDetailPage, ConceptDetailView } from './ConceptDetailPage';

type FetchJson = Record<string, unknown> | Array<Record<string, unknown>>;

function jsonResponse(data: FetchJson) {
  return Promise.resolve({
    ok: true,
    json: async () => data,
  } as Response);
}

function renderConceptDetailPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/concept/7']}>
        <Routes>
          <Route path="/concept/:conceptId" element={<ConceptDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function renderEmbeddedConceptDetail(onSelectConcept: (conceptId: number) => void) {
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
        <ConceptDetailView conceptId={7} showHeader={false} embedded onSelectConcept={onSelectConcept} />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('ConceptDetailPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders concept details, relations, and remarks from the API', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      switch (String(input)) {
        case '/api/concepts/7':
          return jsonResponse({
            id: 7,
            title: 'Rust Ownership',
            description: 'Ownership and borrowing rules.',
            mastery_level: 45,
            interval_days: 3,
            next_review_at: '2026-04-12 08:00:00',
            last_reviewed_at: '2026-04-10 08:00:00',
            review_count: 3,
            created_at: '2026-04-01 10:00:00',
            remark_summary: 'Review aliasing examples.',
            remark_updated_at: '2026-04-11 12:00:00',
            topics: [{ id: 2, title: 'Operating Systems' }],
            remarks: [{ id: 1, content: 'Focus on borrowing edge cases.', created_at: '2026-04-11 12:00:00' }],
            recent_reviews: [{ id: 10, question_asked: 'Explain ownership', user_response: 'Single owner', quality: 4, llm_assessment: 'Solid answer', reviewed_at: '2026-04-10 08:00:00' }],
          });
        case '/api/concepts/7/relations':
          return jsonResponse([
            {
              id: 99,
              other_concept_id: 9,
              other_title: 'Borrow Checker',
              other_mastery: 62,
              relation_type: 'builds_on',
              note: 'Compiler-enforced ownership rules.',
            },
          ]);
        default:
          throw new Error(`Unexpected fetch: ${String(input)}`);
      }
    });

    renderConceptDetailPage();

    expect(await screen.findByRole('heading', { name: 'Rust Ownership' })).toBeInTheDocument();
    expect(await screen.findByText('Ownership and borrowing rules.')).toBeInTheDocument();
    expect(await screen.findByText('Review aliasing examples.')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Operating Systems' })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Borrow Checker' })).toBeInTheDocument();
    expect(await screen.findByText('Focus on borrowing edge cases.')).toBeInTheDocument();
    expect(await screen.findByText('Solid answer · 2026-04-10 08:00:00')).toBeInTheDocument();
  });

  it('uses inline selection for related concepts when embedded', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      switch (String(input)) {
        case '/api/concepts/7':
          return jsonResponse({
            id: 7,
            title: 'Rust Ownership',
            description: 'Ownership and borrowing rules.',
            mastery_level: 45,
            interval_days: 3,
            next_review_at: '2026-04-12 08:00:00',
            last_reviewed_at: '2026-04-10 08:00:00',
            review_count: 3,
            created_at: '2026-04-01 10:00:00',
            remark_summary: 'Review aliasing examples.',
            remark_updated_at: '2026-04-11 12:00:00',
            topics: [{ id: 2, title: 'Operating Systems' }],
            remarks: [],
            recent_reviews: [],
          });
        case '/api/concepts/7/relations':
          return jsonResponse([
            {
              id: 99,
              other_concept_id: 9,
              other_title: 'Borrow Checker',
              other_mastery: 62,
              relation_type: 'builds_on',
              note: 'Compiler-enforced ownership rules.',
            },
          ]);
        default:
          throw new Error(`Unexpected fetch: ${String(input)}`);
      }
    });

    const user = userEvent.setup();
    const onSelectConcept = vi.fn();
    renderEmbeddedConceptDetail(onSelectConcept);

    await user.click(await screen.findByRole('button', { name: 'Borrow Checker' }));

    expect(onSelectConcept).toHaveBeenCalledWith(9);
  });
});