import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TopicDetailPage } from './TopicDetailPage';

type FetchJson = Record<string, unknown> | Array<Record<string, unknown>>;

function jsonResponse(data: FetchJson) {
  return Promise.resolve({
    ok: true,
    json: async () => data,
  } as Response);
}

function renderTopicDetailPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/topic/2']}>
        <Routes>
          <Route path="/topic/:topicId" element={<TopicDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('TopicDetailPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders topic details and ancestry from the API', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      switch (String(input)) {
        case '/api/topics/2':
          return jsonResponse({
            id: 2,
            title: 'Operating Systems',
            description: 'Processes, scheduling, and memory.',
            concepts: [
              {
                id: 7,
                title: 'Rust Ownership',
                mastery_level: 45,
                review_count: 3,
                next_review_at: '2026-04-12 08:00:00',
                latest_remark: 'Focus on borrowing edge cases.',
              },
            ],
            children: [
              { id: 3, title: 'Kernel Design', description: 'Kernel architecture.' },
            ],
            parents: [
              { id: 1, title: 'Systems', description: 'Broad systems thinking.' },
            ],
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
              child_ids: [3],
            },
            {
              id: 3,
              title: 'Kernel Design',
              description: null,
              concept_count: 1,
              avg_mastery: 55,
              due_count: 0,
              parent_ids: [2],
              child_ids: [],
            },
          ]);
        default:
          throw new Error(`Unexpected fetch: ${String(input)}`);
      }
    });

    renderTopicDetailPage();

    expect(await screen.findByRole('heading', { name: 'Operating Systems' })).toBeInTheDocument();
    expect(await screen.findByText('Processes, scheduling, and memory.')).toBeInTheDocument();
    expect((await screen.findAllByRole('link', { name: 'Systems' })).length).toBe(2);
    expect(await screen.findByRole('link', { name: 'Kernel Design' })).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'Rust Ownership' })).toBeInTheDocument();
    expect(await screen.findByText('Focus on borrowing edge cases.')).toBeInTheDocument();
  });
});