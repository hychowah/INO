import { render, screen, waitFor } from '@testing-library/react';
import React from 'react';
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppRouter } from './routes';

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

describe('AppRouter', () => {
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

  it('redirects legacy knowledge and progress aliases to the canonical consolidated routes', async () => {
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

    window.history.replaceState({}, '', '/graph');
    const { unmount } = render(<AppRouter />);

    expect(await screen.findByRole('heading', { name: 'Knowledge explorer' })).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.pathname).toBe('/knowledge/graph');
    });
    unmount();

    window.history.replaceState({}, '', '/reviews');
    render(<AppRouter />);

    expect(await screen.findByRole('heading', { name: 'Review performance' })).toBeInTheDocument();
    await waitFor(() => {
      expect(window.location.pathname).toBe('/progress');
    });
  });
});