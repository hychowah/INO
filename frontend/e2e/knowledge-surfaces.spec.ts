import { expect, test } from '@playwright/test';

function json(body: unknown) {
  return {
    contentType: 'application/json',
    body: JSON.stringify(body),
  };
}

test('concepts page renders and filters by topic', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    switch (`${url.pathname}${url.search}`) {
      case '/api/topics/flat':
        await route.fulfill(json([
          { id: 1, title: 'Systems' },
          { id: 2, title: 'Compilers' },
        ]));
        return;
      case '/api/concepts?sort=next_review_at&order=asc&page=1&per_page=20':
        await route.fulfill(json({
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
            {
              id: 9,
              title: 'Type Inference',
              mastery_level: 81,
              interval_days: 6,
              review_count: 5,
              next_review_at: '2999-04-17 09:00:00',
              last_reviewed_at: '2026-04-11 09:00:00',
              latest_remark: 'Constraint solving is stable.',
              topics: [{ id: 2, title: 'Compilers' }],
            },
          ],
          total: 2,
          page: 1,
          per_page: 20,
        }));
        return;
      case '/api/concepts?topic_id=1&sort=next_review_at&order=asc&page=1&per_page=20':
        await route.fulfill(json({
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
        }));
        return;
      default:
        await route.abort();
    }
  });

  await page.goto('/concepts');

  await expect(page.getByRole('heading', { name: 'Concepts' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Borrow Checker' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Type Inference' })).toBeVisible();

  await page.getByRole('button', { name: 'Systems' }).click();

  await expect(page.getByRole('link', { name: 'Borrow Checker' })).toBeVisible();
  await expect(page.getByText('1 concept matched. Page 1 of 1.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Type Inference' })).toHaveCount(0);
});

test('graph page renders and refetches when topic filter changes', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    switch (`${url.pathname}${url.search}`) {
      case '/api/graph?max_nodes=500':
        await route.fulfill(json({
          concept_nodes: [
            { id: 7, title: 'Borrow Checker', description: 'Ownership rules', review_count: 3, mastery_level: 62, next_review_at: '2026-04-20 08:00:00', interval_days: 4, topic_names: 'Systems', topic_ids: [1] },
            { id: 9, title: 'Type Inference', description: 'Constraint solving', review_count: 5, mastery_level: 81, next_review_at: '2026-04-21 08:00:00', interval_days: 6, topic_names: 'Compilers', topic_ids: [2] },
          ],
          topic_nodes: [
            { id: 1, title: 'Systems' },
            { id: 2, title: 'Compilers' },
          ],
          concept_edges: [
            { concept_id_low: 7, concept_id_high: 9, relation_type: 'builds_on', note: 'Shared foundation' },
          ],
          topic_edges: [
            { parent_id: 1, child_id: 2 },
          ],
          concept_topic_edges: [
            { concept_id: 7, topic_id: 1 },
            { concept_id: 9, topic_id: 2 },
          ],
          total_concepts: 2,
        }));
        return;
      case '/api/graph?topic_id=1&max_nodes=500':
        await route.fulfill(json({
          concept_nodes: [
            { id: 7, title: 'Borrow Checker', description: 'Ownership rules', review_count: 3, mastery_level: 62, next_review_at: '2026-04-20 08:00:00', interval_days: 4, topic_names: 'Systems', topic_ids: [1] },
          ],
          topic_nodes: [
            { id: 1, title: 'Systems' },
          ],
          concept_edges: [],
          topic_edges: [],
          concept_topic_edges: [
            { concept_id: 7, topic_id: 1 },
          ],
          total_concepts: 1,
        }));
        return;
      default:
        await route.abort();
    }
  });

  await page.goto('/graph');

  await expect(page.getByRole('heading', { name: 'Graph' })).toBeVisible();
  await expect(page.getByText('2 concepts, 2 topics, 4 edges.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Legend' })).toBeVisible();

  await page.getByRole('combobox').nth(0).selectOption('1');

  await expect(page.getByText('1 concepts, 1 topics, 1 edges.')).toBeVisible();
});