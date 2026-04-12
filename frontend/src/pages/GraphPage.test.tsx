import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { GraphPage } from './GraphPage';

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

function renderGraphPage() {
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
        <GraphPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('GraphPage', () => {
  beforeAll(() => {
    class ResizeObserverMock {
      observe() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', ResizeObserverMock);
  });

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders graph data and refetches when a topic filter is applied', async () => {
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
        case '/api/graph?topic_id=2&max_nodes=500':
          return jsonResponse({
            concept_nodes: [
              { id: 7, title: 'Borrow Checker', description: 'Ownership rules', review_count: 3, mastery_level: 62, next_review_at: '2026-04-20 08:00:00', interval_days: 4, topic_names: 'Systems', topic_ids: [2] },
            ],
            topic_nodes: [{ id: 2, title: 'Systems' }],
            concept_edges: [],
            topic_edges: [],
            concept_topic_edges: [{ concept_id: 7, topic_id: 2 }],
            total_concepts: 1,
          });
        default:
          throw new Error(`Unexpected fetch: ${String(input)}`);
      }
    });

    const user = userEvent.setup();
    renderGraphPage();

    expect(await screen.findByRole('heading', { name: 'Graph' })).toBeInTheDocument();
    expect(await screen.findByTestId('force-graph')).toHaveTextContent('4 nodes / 4 links');

    await user.selectOptions(screen.getByRole('combobox'), '2');

    await waitFor(() => {
      expect(screen.getByTestId('force-graph')).toHaveTextContent('2 nodes / 1 links');
    });
  });
});