import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConceptsListPage } from './ConceptsListPage';

function jsonResponse(data: Record<string, unknown> | Array<Record<string, unknown>>) {
  return Promise.resolve({
    ok: true,
    json: async () => data,
  } as Response);
}

function renderConceptsPage() {
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
        <ConceptsListPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('ConceptsListPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    window.sessionStorage.clear();
  });

  it('renders concepts and deletes a concept after confirmation', async () => {
    let listCalls = 0;
    let filteredCalls = 0;

    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      const path = String(input);
      if (path === '/api/topics/flat') {
        return jsonResponse([
          { id: 1, title: 'Systems' },
          { id: 2, title: 'Compilers' },
        ]);
      }

      if (path === '/api/concepts?sort=next_review_at&order=asc&page=1&per_page=20') {
        listCalls += 1;
        return jsonResponse({
          items: listCalls === 1 ? [
            {
              id: 7,
              title: 'Borrow Checker',
              mastery_level: 62,
              interval_days: 4,
              review_count: 3,
              next_review_at: '2999-04-15 09:00:00',
              last_reviewed_at: '2026-04-10 09:00:00',
              latest_remark: 'Still mixing ownership and borrowing edge cases.',
              topics: [{ id: 1, title: 'Systems' }],
            },
          ] : [],
          total: listCalls === 1 ? 1 : 0,
          page: 1,
          per_page: 20,
        });
      }

      if (path === '/api/concepts?topic_id=1&sort=next_review_at&order=asc&page=1&per_page=20') {
        filteredCalls += 1;
        return jsonResponse({
          items: filteredCalls === 1 ? [
            {
              id: 7,
              title: 'Borrow Checker',
              mastery_level: 62,
              interval_days: 4,
              review_count: 3,
              next_review_at: '2999-04-15 09:00:00',
              last_reviewed_at: '2026-04-10 09:00:00',
              latest_remark: 'Still mixing ownership and borrowing edge cases.',
              topics: [{ id: 1, title: 'Systems' }],
            },
          ] : [],
          total: filteredCalls === 1 ? 1 : 0,
          page: 1,
          per_page: 20,
        });
      }

      if (path === '/api/concepts/7' && init?.method === 'DELETE') {
        return jsonResponse({ message: 'Concept 7 deleted.' });
      }

      throw new Error(`Unexpected fetch: ${path}`);
    });

    const user = userEvent.setup();
    renderConceptsPage();

    expect(await screen.findByRole('heading', { name: 'Concepts' })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Borrow Checker' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Systems' }));
    expect(await screen.findByDisplayValue('Systems')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Delete' }));
    expect(await screen.findByText('Delete Concept')).toBeInTheDocument();
    expect(screen.getAllByText('Borrow Checker')).toHaveLength(2);

    await user.click(screen.getAllByRole('button', { name: 'Delete' })[1]);

    await waitFor(() => {
      expect(screen.queryByRole('link', { name: 'Borrow Checker' })).not.toBeInTheDocument();
    });
    expect(await screen.findByText('No concepts matched the current filters.')).toBeInTheDocument();
  });
});