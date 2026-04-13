import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppShell } from './AppShell';

function jsonResponse(data: Record<string, unknown> | Array<Record<string, unknown>>) {
  return Promise.resolve({
    ok: true,
    json: async () => data,
  } as Response);
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location-probe">{`${location.pathname}${location.search}`}</div>;
}

function renderShell(initialEntry = '/') {
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
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<><LocationProbe /><div>Dashboard stub</div></>} />
            <Route path="/progress" element={<><LocationProbe /><div>Progress stub</div></>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe('AppShell', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    class ResizeObserverMock {
      observe() {}
      unobserve() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', ResizeObserverMock);
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: vi.fn(),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('opens the activity drawer without replacing the current page and clears the query on close', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      switch (String(input)) {
        case '/api/actions/filters':
          return jsonResponse({ actions: ['assess'], sources: ['api'] });
        case '/api/actions?time=all&page=1&per_page=20':
          return jsonResponse({
            items: [
              {
                id: 11,
                action: 'assess',
                params: JSON.stringify({ concept_id: 7, quality: 4 }),
                result_type: 'success',
                result: JSON.stringify({ message: 'ok' }),
                source: 'api',
                created_at: '2026-04-12 09:00:00',
              },
            ],
            total: 1,
            page: 1,
            per_page: 20,
          });
        default:
          throw new Error(`Unexpected fetch: ${String(input)}`);
      }
    });

    const user = userEvent.setup();
    renderShell();

    expect(screen.getByText('Dashboard stub')).toBeInTheDocument();
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/');

    await user.click(screen.getByRole('button', { name: /activity operational log/i }));

    expect(await screen.findByText('Dashboard stub')).toBeInTheDocument();
    expect(await screen.findByText('Activity log')).toBeInTheDocument();
    expect(await screen.findByText('concept_id: 7 · quality: 4')).toBeInTheDocument();
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/?activity=1');

    await user.click(screen.getByRole('button', { name: /close/i }));

    await waitFor(() => {
      expect(screen.queryByText('concept_id: 7 · quality: 4')).not.toBeInTheDocument();
    });
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/');
  });

  it('opens the command palette with Ctrl+K and navigates to another surface', async () => {
    const user = userEvent.setup();
    renderShell();

    await user.keyboard('{Control>}k{/Control}');

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Jump to a surface or action...')).toBeInTheDocument();

    await user.click(within(dialog).getByText('Progress'));

    await waitFor(() => {
      expect(screen.getByText('Progress stub')).toBeInTheDocument();
    });
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/progress');
  });
});