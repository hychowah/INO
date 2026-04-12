import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App, resolveBackendHref } from './App';

type FetchJson = Record<string, unknown>;

function jsonResponse(data: FetchJson) {
  return Promise.resolve({
    ok: true,
    json: async () => data,
  } as Response);
}

describe('App', () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it('inserts a command chip into the composer', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      if (String(input) === '/api/chat/bootstrap') {
        return jsonResponse({
          history: [],
          commands: [{ label: 'Review', command: '/review' }],
        });
      }
      throw new Error(`Unexpected fetch: ${String(input)}`);
    });

    const user = userEvent.setup();
    render(<App />);

    await user.click(await screen.findByRole('button', { name: 'Review' }));

    expect(screen.getByPlaceholderText(/ask a question/i)).toHaveValue('/review');
  });

  it('routes backend page links to the FastAPI origin when running on the Vite dev server', () => {
    const devLocation = { protocol: 'http:', hostname: '127.0.0.1', port: '5173' } as Location;

    expect(resolveBackendHref('/', devLocation)).toBe('http://127.0.0.1:8080/');
    expect(resolveBackendHref('/topics', devLocation)).toBe('http://127.0.0.1:8080/topics');
    expect(resolveBackendHref('/concept/7', devLocation)).toBe('http://127.0.0.1:8080/concept/7');
    expect(resolveBackendHref('/chat', devLocation)).toBe('http://127.0.0.1:8080/chat');
  });

  it('keeps relative backend links outside the Vite dev server', () => {
    const appLocation = { protocol: 'http:', hostname: '127.0.0.1', port: '8080' } as Location;

    expect(resolveBackendHref('/', appLocation)).toBe('/');
    expect(resolveBackendHref('/topics', appLocation)).toBe('/topics');
  });

  it('persists a pending confirmation and blocks normal messages until resolved', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      if (String(input) === '/api/chat/bootstrap') {
        return jsonResponse({
          history: [],
          commands: [],
        });
      }

      if (String(input) === '/api/chat') {
        const body = JSON.parse(String(init?.body || '{}')) as { message?: string };
        if (body.message === '/review') {
          return jsonResponse({
            type: 'pending_confirm',
            message: 'Add this concept?',
            pending_action: {
              action: 'add_concept',
              message: 'Add this concept?',
              params: { title: 'Rust' },
            },
          });
        }
        throw new Error(`Unexpected chat message: ${body.message}`);
      }

      throw new Error(`Unexpected fetch: ${String(input)}`);
    });

    const user = userEvent.setup();
    render(<App />);

    const input = await screen.findByPlaceholderText(/ask a question/i);
    await user.type(input, '/review');
    await user.keyboard('{Enter}');

    await screen.findByText('Pending confirmation');
    expect(JSON.parse(window.sessionStorage.getItem('learning-agent-pending-action') || '{}')).toMatchObject({
      action: 'add_concept',
      params: { title: 'Rust' },
    });

    await user.clear(input);
    await user.type(input, 'hello');
    await user.keyboard('{Enter}');

    expect(await screen.findByText('Resolve the pending action before sending a new message.')).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
  });

  it('confirms a pending action, clears storage, and appends the follow-up reply', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      if (String(input) === '/api/chat/bootstrap') {
        return jsonResponse({
          history: [],
          commands: [],
        });
      }

      if (String(input) === '/api/chat') {
        return jsonResponse({
          type: 'pending_confirm',
          message: 'Add this concept?',
          pending_action: {
            action: 'add_concept',
            message: 'Add this concept?',
            params: { title: 'Rust' },
          },
        });
      }

      if (String(input) === '/api/chat/confirm') {
        const body = JSON.parse(String(init?.body || '{}')) as { action_data?: { action?: string; params?: { title?: string } } };
        expect(body.action_data?.action).toBe('add_concept');
        expect(body.action_data?.params?.title).toBe('Rust');
        return jsonResponse({
          type: 'reply',
          message: 'Add this concept?\n\n✅ Added concept #7',
          pending_action: null,
        });
      }

      throw new Error(`Unexpected fetch: ${String(input)}`);
    });

    const user = userEvent.setup();
    render(<App />);

    const input = await screen.findByPlaceholderText(/ask a question/i);
    await user.type(input, '/review');
    await user.keyboard('{Enter}');

    await user.click(await screen.findByRole('button', { name: 'Confirm' }));

    expect(await screen.findByText('Confirmed: add concept')).toBeInTheDocument();
    expect(await screen.findByText('✅ Added concept #7')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText('Pending confirmation')).not.toBeInTheDocument();
    });
    expect(window.sessionStorage.getItem('learning-agent-pending-action')).toBeNull();
  });

  it('removes a proposal review item after a successful inline action', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      if (String(input) === '/api/chat/bootstrap') {
        return jsonResponse({
          history: [],
          commands: [],
        });
      }

      if (String(input) === '/api/chat') {
        const body = JSON.parse(String(init?.body || '{}')) as { message?: string };
        if (body.message === '/maintain') {
          return jsonResponse({
            type: 'reply',
            message: 'Maintenance proposals ready.',
            pending_action: null,
            actions: [
              {
                type: 'proposal_review',
                title: 'Maintenance proposals',
                items: [
                  {
                    id: 'proposal-1',
                    label: 'Rename topic',
                    detail: 'Rename target: Rust Basics',
                    buttons: [
                      {
                        label: 'Approve',
                        style: 'primary',
                        ui_effect: 'remove_item',
                        action: { kind: 'apply_maintenance_actions', actions: [{ action: 'update_topic' }] },
                      },
                    ],
                  },
                ],
              },
            ],
          });
        }
      }

      if (String(input) === '/api/chat/action') {
        return jsonResponse({
          type: 'reply',
          message: 'Applied maintenance change.',
          pending_action: null,
        });
      }

      throw new Error(`Unexpected fetch: ${String(input)}`);
    });

    const user = userEvent.setup();
    render(<App />);

    const input = await screen.findByPlaceholderText(/ask a question/i);
    await user.type(input, '/maintain');
    await user.keyboard('{Enter}');

    const approveButton = await screen.findByRole('button', { name: 'Approve' });
    expect(screen.getByText('Rename topic')).toBeInTheDocument();

    await user.click(approveButton);

    expect(await screen.findByText('Applied maintenance change.')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText('Rename topic')).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
    });
  });

  it('submits a multiple-choice action and removes the choice block after success', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      if (String(input) === '/api/chat/bootstrap') {
        return jsonResponse({
          history: [],
          commands: [],
        });
      }

      if (String(input) === '/api/chat') {
        const body = JSON.parse(String(init?.body || '{}')) as { message?: string };
        if (body.message === '/review') {
          return jsonResponse({
            type: 'reply',
            message: 'Choose the best answer.',
            pending_action: null,
            actions: [
              {
                type: 'multiple_choice',
                title: 'Choose an answer',
                choices: [
                  {
                    label: 'Borrowing',
                    action: { kind: 'send_message', message: 'I choose: Borrowing' },
                  },
                ],
              },
            ],
          });
        }
      }

      if (String(input) === '/api/chat/action') {
        const body = JSON.parse(String(init?.body || '{}')) as { action?: { kind?: string; message?: string } };
        expect(body.action).toMatchObject({ kind: 'send_message', message: 'I choose: Borrowing' });
        return jsonResponse({
          type: 'reply',
          message: 'Correct.',
          pending_action: null,
        });
      }

      throw new Error(`Unexpected fetch: ${String(input)}`);
    });

    const user = userEvent.setup();
    render(<App />);

    const input = await screen.findByPlaceholderText(/ask a question/i);
    await user.type(input, '/review');
    await user.keyboard('{Enter}');

    const choiceButton = await screen.findByRole('button', { name: 'Borrowing' });
    await user.click(choiceButton);

    expect(await screen.findByText('Correct.')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Borrowing' })).not.toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/chat/action',
      expect.objectContaining({
        method: 'POST',
      })
    );
  });

  it('dismisses a button group without calling the action endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
      if (String(input) === '/api/chat/bootstrap') {
        return jsonResponse({
          history: [],
          commands: [],
        });
      }

      if (String(input) === '/api/chat') {
        const body = JSON.parse(String(init?.body || '{}')) as { message?: string };
        if (body.message === '/due') {
          return jsonResponse({
            type: 'reply',
            message: 'Quiz follow-up',
            pending_action: null,
            actions: [
              {
                type: 'button_group',
                title: 'Quiz follow-up',
                buttons: [
                  {
                    label: 'Done',
                    style: 'secondary',
                    action: { kind: 'dismiss' },
                  },
                ],
              },
            ],
          });
        }
      }

      throw new Error(`Unexpected fetch: ${String(input)}`);
    });

    const user = userEvent.setup();
    render(<App />);

    const input = await screen.findByPlaceholderText(/ask a question/i);
    await user.type(input, '/due');
    await user.keyboard('{Enter}');

    const doneButton = await screen.findByRole('button', { name: 'Done' });
    await user.click(doneButton);

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'Done' })).not.toBeInTheDocument();
    });
    expect(screen.getByText('Quiz follow-up')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});