import { expect, test } from '@playwright/test';

function json(body: unknown) {
  return {
    contentType: 'application/json',
    body: JSON.stringify(body),
  };
}

function sse(events: Array<{ event: string; data: Record<string, unknown> }>) {
  return {
    contentType: 'text/event-stream',
    body: events.map(({ event, data }) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join(''),
  };
}

test('chat streams a pending confirmation and completes the confirm flow', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();

    if (url.pathname === '/api/chat/bootstrap' && method === 'GET') {
      await route.fulfill(json({
        history: [],
        commands: [
          { label: 'Review', command: '/review' },
        ],
      }));
      return;
    }

    if (url.pathname === '/api/chat/stream' && method === 'POST') {
      const body = JSON.parse(route.request().postData() || '{}') as { message?: string };

      if (body.message === '/review') {
        await route.fulfill(sse([
          { event: 'status', data: { message: 'Waiting for the learning agent...' } },
          {
            event: 'done',
            data: {
              type: 'pending_confirm',
              message: 'Add this concept?',
              pending_action: {
                action: 'add_concept',
                message: 'Add this concept?',
                params: { title: 'Rust Ownership' },
              },
            },
          },
        ]));
        return;
      }

      await route.abort();
      return;
    }

    if (url.pathname === '/api/chat/confirm' && method === 'POST') {
      const body = JSON.parse(route.request().postData() || '{}') as {
        action_data?: { action?: string; params?: { title?: string } };
      };

      expect(body.action_data?.action).toBe('add_concept');
      expect(body.action_data?.params?.title).toBe('Rust Ownership');

      await route.fulfill(json({
        type: 'reply',
        message: 'Add this concept?\n\n✅ Added concept #7',
        pending_action: null,
      }));
      return;
    }

    await route.abort();
  });

  await page.goto('/chat');

  await expect(page.getByRole('heading', { name: 'Chat' })).toBeVisible();

  const composer = page.getByPlaceholder('Ask a question, request a quiz, or tell the agent what you want to learn...');
  await composer.fill('/review');
  await composer.press('Enter');

  await expect(page.getByText('Add this concept?').first()).toBeVisible();
  await expect(page.getByText('Pending confirmation')).toBeVisible();

  await page.getByRole('button', { name: 'Confirm' }).click();

  await expect(page.getByText('Confirmed: add concept')).toBeVisible();
  await expect(page.getByText('✅ Added concept #7')).toBeVisible();
  await expect(page.getByText('Pending confirmation')).toHaveCount(0);
});

test('chat streams a rich-text reply and dismisses an inline action block', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();

    if (url.pathname === '/api/chat/bootstrap' && method === 'GET') {
      await route.fulfill(json({
        history: [],
        commands: [],
      }));
      return;
    }

    if (url.pathname === '/api/chat/stream' && method === 'POST') {
      const body = JSON.parse(route.request().postData() || '{}') as { message?: string };

      if (body.message === 'Explain ownership') {
        await route.fulfill(sse([
          { event: 'status', data: { message: 'Waiting for the learning agent...' } },
          {
            event: 'done',
            data: {
              type: 'reply',
              message: '## Ownership\n\n- Rust uses **borrowing** to avoid copies.\n- Review [concept:7] next.',
              pending_action: null,
              actions: [
                {
                  type: 'button_group',
                  title: 'Follow-up',
                  buttons: [
                    {
                      label: 'Done',
                      style: 'secondary',
                      action: { kind: 'dismiss' },
                    },
                  ],
                },
              ],
            },
          },
        ]));
        return;
      }

      await route.abort();
      return;
    }

    await route.abort();
  });

  await page.goto('/chat');

  const composer = page.getByPlaceholder('Ask a question, request a quiz, or tell the agent what you want to learn...');
  await composer.fill('Explain ownership');
  await composer.press('Enter');

  await expect(page.getByRole('heading', { name: 'OWNERSHIP' })).toBeVisible();
  await expect(page.getByText('borrowing')).toBeVisible();
  await expect(page.getByRole('link', { name: 'concept:7' })).toHaveAttribute('href', '/concept/7');
  await expect(page.getByRole('button', { name: 'Done' })).toBeVisible();

  await page.getByRole('button', { name: 'Done' }).click();

  await expect(page.getByRole('button', { name: 'Done' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'OWNERSHIP' })).toBeVisible();
});

test('chat streams a reply and runs a server-backed inline action', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();

    if (url.pathname === '/api/chat/bootstrap' && method === 'GET') {
      await route.fulfill(json({
        history: [],
        commands: [],
      }));
      return;
    }

    if (url.pathname === '/api/chat/stream' && method === 'POST') {
      const body = JSON.parse(route.request().postData() || '{}') as { message?: string };

      if (body.message === 'What should I study next?') {
        await route.fulfill(sse([
          { event: 'status', data: { message: 'Waiting for the learning agent...' } },
          {
            event: 'done',
            data: {
              type: 'reply',
              message: 'You should review your next due concept.',
              pending_action: null,
              actions: [
                {
                  type: 'button_group',
                  title: 'Next step',
                  buttons: [
                    {
                      label: 'Quiz me next',
                      style: 'primary',
                      action: {
                        kind: 'send_message',
                        message: '[BUTTON] Quiz me on the next due concept',
                      },
                    },
                  ],
                },
              ],
            },
          },
        ]));
        return;
      }

      await route.abort();
      return;
    }

    if (url.pathname === '/api/chat/action' && method === 'POST') {
      const body = JSON.parse(route.request().postData() || '{}') as {
        action?: { kind?: string; message?: string };
      };

      expect(body.action).toMatchObject({
        kind: 'send_message',
        message: '[BUTTON] Quiz me on the next due concept',
      });

      await route.fulfill(json({
        type: 'reply',
        message: 'Queued the next quiz.',
        pending_action: null,
      }));
      return;
    }

    await route.abort();
  });

  await page.goto('/chat');

  const composer = page.getByPlaceholder('Ask a question, request a quiz, or tell the agent what you want to learn...');
  await composer.fill('What should I study next?');
  await composer.press('Enter');

  await expect(page.getByText('You should review your next due concept.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Quiz me next' })).toBeVisible();

  await page.getByRole('button', { name: 'Quiz me next' }).click();

  await expect(page.getByText('Queued the next quiz.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Quiz me next' })).toHaveCount(0);
});