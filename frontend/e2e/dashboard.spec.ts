import { expect, test } from '@playwright/test';

function json(body: unknown) {
  return {
    contentType: 'application/json',
    body: JSON.stringify(body),
  };
}

test('dashboard renders from mocked API responses', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    switch (`${url.pathname}${url.search}`) {
      case '/api/stats':
        await route.fulfill(json({
          total_concepts: 12,
          total_reviews: 30,
          due_now: 4,
          avg_mastery: 61.5,
          reviews_last_7d: 9,
        }));
        return;
      case '/api/due?limit=10':
        await route.fulfill(json([
          { id: 7, title: 'Rust Ownership', mastery_level: 45, next_review_at: '2026-04-12 08:00:00' },
        ]));
        return;
      case '/api/action-summary?days=7':
        await route.fulfill(json({
          days: 7,
          total: 6,
          today_total: 2,
          by_action: { assess: 3, add_concept: 1 },
          today_by_action: { assess: 2 },
        }));
        return;
      case '/api/topic-map':
        await route.fulfill(json([
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
        ]));
        return;
      default:
        await route.abort();
    }
  });

  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible();
  await expect(page.getByText('Rust Ownership')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Systems', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Operating Systems', exact: true })).toBeVisible();
  await expect(page.getByText(/Today: .*2 reviews/i)).toBeVisible();
});