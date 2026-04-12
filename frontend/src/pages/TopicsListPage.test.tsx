import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TopicsListPage } from './TopicsListPage';

function jsonResponse(data: Record<string, unknown> | Array<Record<string, unknown>>) {
  return Promise.resolve({
    ok: true,
    json: async () => data,
  } as Response);
}

function renderTopicsListPage() {
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
        <TopicsListPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('TopicsListPage', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it('renders topic hierarchy and filters by search query', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      if (String(input) === '/api/topic-map') {
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
          {
            id: 3,
            title: 'Compiler Design',
            description: null,
            concept_count: 4,
            avg_mastery: 62,
            due_count: 0,
            parent_ids: [],
            child_ids: [],
          },
        ]);
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });

    const user = userEvent.setup();
    renderTopicsListPage();

    expect(await screen.findByRole('heading', { name: 'Topics' })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Systems' })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Operating Systems' })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Compiler Design' })).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText('Search topics...'), 'compiler');

    expect(await screen.findByRole('link', { name: 'Compiler Design' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Operating Systems' })).not.toBeInTheDocument();
  });
});