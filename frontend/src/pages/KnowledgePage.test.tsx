import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { KnowledgePage } from './KnowledgePage';

vi.mock('react-force-graph-2d', () => ({
  default: React.forwardRef(function MockForceGraph2D(props: { graphData: { nodes: unknown[]; links: unknown[] } }, ref) {
    React.useImperativeHandle(ref, () => ({
      d3Force: () => undefined,
      d3ReheatSimulation: () => undefined,
      zoomToFit: () => undefined,
      centerAt: () => undefined,
      zoom: () => undefined,
    }));

    return <div data-testid="force-graph">{props.graphData.nodes.length} nodes / {props.graphData.links.length} links</div>;
  }),
}));

function jsonResponse(data: Record<string, unknown> | Array<Record<string, unknown>>) {
  return Promise.resolve({
    ok: true,
    json: async () => data,
  } as Response);
}

function renderKnowledgePage(initialEntry: string) {
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
        <KnowledgePage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('KnowledgePage', () => {
  beforeAll(() => {
    class ResizeObserverMock {
      observe() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', ResizeObserverMock);
  });

  beforeEach(() => {
    vi.restoreAllMocks();
    window.sessionStorage.clear();
  });

  it('renders the topics tab on /knowledge and shows inline topic detail', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const path = String(input);
      if (path === '/api/topic-map') {
        return jsonResponse([
          {
            id: 1,
            title: 'Systems',
            description: null,
            concept_count: 3,
            avg_mastery: 50,
            due_count: 1,
            parent_ids: [],
            child_ids: [],
          },
        ]);
      }
      if (path === '/api/topics/1') {
        return jsonResponse({
          id: 1,
          title: 'Systems',
          description: 'Broad systems thinking.',
          concepts: [
            {
              id: 7,
              title: 'Borrow Checker',
              mastery_level: 62,
              review_count: 3,
              next_review_at: '2999-04-15 09:00:00',
              latest_remark: 'Still mixing ownership and borrowing edge cases.',
            },
          ],
          children: [],
          parents: [],
        });
      }
      throw new Error(`Unexpected fetch: ${path}`);
    });

    const user = userEvent.setup();
    renderKnowledgePage('/knowledge');

    expect(await screen.findByRole('heading', { name: 'Knowledge explorer' })).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Topic Explorer' })).toBeInTheDocument();
  expect(await screen.findByRole('button', { name: 'Systems' })).toBeInTheDocument();
  expect(screen.getByText('Topic detail panel')).toBeInTheDocument();

  await user.click(screen.getByRole('button', { name: 'Systems' }));

  expect(await screen.findByRole('heading', { name: 'Systems' })).toBeInTheDocument();
  expect(await screen.findByText('Broad systems thinking.')).toBeInTheDocument();
  expect(await screen.findByRole('link', { name: 'Borrow Checker' })).toBeInTheDocument();
  });

  it('renders the concepts tab directly on /knowledge/concepts and shows inline concept detail', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const path = String(input);
      if (path === '/api/topics/flat') {
        return jsonResponse([{ id: 1, title: 'Systems' }]);
      }
      if (path === '/api/concepts?sort=next_review_at&order=asc&page=1&per_page=20') {
        return jsonResponse({
          items: [
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
          ],
          total: 1,
          page: 1,
          per_page: 20,
        });
      }
      if (path === '/api/concepts/7') {
        return jsonResponse({
          id: 7,
          title: 'Borrow Checker',
          description: 'Compiler-enforced ownership rules.',
          mastery_level: 62,
          interval_days: 4,
          next_review_at: '2026-04-15 09:00:00',
          last_reviewed_at: '2026-04-10 09:00:00',
          review_count: 3,
          created_at: '2026-04-01 10:00:00',
          remark_summary: 'Still mixing ownership and borrowing edge cases.',
          remark_updated_at: '2026-04-11 12:00:00',
          topics: [{ id: 1, title: 'Systems' }],
          remarks: [{ id: 1, content: 'Focus on ownership transfer examples.', created_at: '2026-04-11 12:00:00' }],
          recent_reviews: [{ id: 10, question_asked: 'What is ownership?', user_response: 'A single owner model', quality: 4, llm_assessment: 'Solid answer', reviewed_at: '2026-04-10 08:00:00' }],
        });
      }
      if (path === '/api/concepts/7/relations') {
        return jsonResponse([
          {
            id: 99,
            other_concept_id: 9,
            other_title: 'Rust Ownership',
            other_mastery: 45,
            relation_type: 'builds_on',
            note: 'Ownership rules shape the borrow checker.',
          },
        ]);
      }
      if (path === '/api/concepts/9') {
        return jsonResponse({
          id: 9,
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
          topics: [{ id: 1, title: 'Systems' }],
          remarks: [{ id: 1, content: 'Focus on borrowing edge cases.', created_at: '2026-04-11 12:00:00' }],
          recent_reviews: [{ id: 10, question_asked: 'Explain ownership', user_response: 'Single owner', quality: 4, llm_assessment: 'Solid answer', reviewed_at: '2026-04-10 08:00:00' }],
        });
      }
      if (path === '/api/concepts/9/relations') {
        return jsonResponse([]);
      }
      throw new Error(`Unexpected fetch: ${path}`);
    });

    const user = userEvent.setup();
    renderKnowledgePage('/knowledge/concepts');

    expect(await screen.findByRole('heading', { name: 'Filters' })).toBeInTheDocument();
    expect(await screen.findByDisplayValue('Ascending')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Borrow Checker' })).toBeInTheDocument();
    expect(screen.getByText('Concept detail panel')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Borrow Checker' }));

    expect(await screen.findByRole('heading', { name: 'Borrow Checker' })).toBeInTheDocument();
    expect(await screen.findByText('Compiler-enforced ownership rules.')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Rust Ownership' }));
    expect(await screen.findByRole('heading', { name: 'Rust Ownership' })).toBeInTheDocument();
  });

  it('renders the graph tab on the legacy /graph alias', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      switch (String(input)) {
        case '/api/graph?max_nodes=500':
          return jsonResponse({
            concept_nodes: [
              { id: 7, title: 'Borrow Checker', description: 'Ownership rules', review_count: 3, mastery_level: 62, next_review_at: '2026-04-20 08:00:00', interval_days: 4, topic_names: 'Systems', topic_ids: [2] },
              { id: 9, title: 'Type Inference', description: 'Inference constraints', review_count: 4, mastery_level: 81, next_review_at: '2026-04-21 08:00:00', interval_days: 6, topic_names: 'Compilers', topic_ids: [3] },
            ],
            topic_nodes: [
              { id: 2, title: 'Systems' },
              { id: 3, title: 'Compilers' },
            ],
            concept_edges: [{ concept_id_low: 7, concept_id_high: 9, relation_type: 'builds_on', note: 'Shared foundation' }],
            topic_edges: [{ parent_id: 2, child_id: 3 }],
            concept_topic_edges: [{ concept_id: 7, topic_id: 2 }, { concept_id: 9, topic_id: 3 }],
            total_concepts: 2,
          });
        default:
          throw new Error(`Unexpected fetch: ${String(input)}`);
      }
    });

    renderKnowledgePage('/graph');

    expect(await screen.findByRole('heading', { name: 'Filters' })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByTestId('force-graph')).toHaveTextContent('4 nodes / 4 links');
    });
  });
});