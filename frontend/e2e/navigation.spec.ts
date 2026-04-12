import { expect, test } from '@playwright/test';

function json(body: unknown) {
  return {
    contentType: 'application/json',
    body: JSON.stringify(body),
  };
}

test('reviews page links through to concept detail', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    switch (`${route.request().method()} ${url.pathname}${url.search}`) {
      case 'GET /api/reviews?limit=50':
        await route.fulfill(json([
          {
            id: 101,
            concept_id: 7,
            concept_title: 'Borrow Checker',
            question_asked: 'What problem does the borrow checker solve?',
            user_response: 'It prevents invalid references.',
            quality: 4,
            llm_assessment: 'Good answer with the right emphasis.',
            reviewed_at: '2026-04-12 09:00:00',
          },
        ]));
        return;
      case 'GET /api/concepts/7':
        await route.fulfill(json({
          id: 7,
          title: 'Borrow Checker',
          description: 'Rust ownership validation rules.',
          mastery_level: 62,
          interval_days: 4,
          next_review_at: '2026-04-20 08:00:00',
          last_reviewed_at: '2026-04-12 09:00:00',
          review_count: 3,
          created_at: '2026-04-01 10:00:00',
          remark_summary: 'Still mixing lifetime edge cases.',
          remark_updated_at: '2026-04-12 09:05:00',
          topics: [{ id: 2, title: 'Operating Systems' }],
          remarks: [
            { id: 1, content: 'Focus on aliasing rules next.', created_at: '2026-04-12 09:05:00' },
          ],
          recent_reviews: [
            {
              id: 101,
              question_asked: 'What problem does the borrow checker solve?',
              user_response: 'It prevents invalid references.',
              quality: 4,
              llm_assessment: 'Good answer with the right emphasis.',
              reviewed_at: '2026-04-12 09:00:00',
            },
          ],
        }));
        return;
      case 'GET /api/concepts/7/relations':
        await route.fulfill(json([
          {
            id: 55,
            other_concept_id: 8,
            other_title: 'Ownership',
            other_mastery: 71,
            relation_type: 'builds_on',
            note: 'Borrow checking enforces ownership rules.',
          },
        ]));
        return;
      default:
        await route.abort();
    }
  });

  await page.goto('/reviews');

  await expect(page.getByRole('heading', { name: 'Review Log' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Borrow Checker' })).toBeVisible();

  await page.getByRole('link', { name: 'Borrow Checker' }).click();

  await expect(page.getByText('Borrow Checker').nth(0)).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Recent Reviews' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Relations' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Ownership' })).toBeVisible();
});

test('topics search filters the tree and navigates into topic detail', async ({ page }) => {
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());

    switch (`${route.request().method()} ${url.pathname}${url.search}`) {
      case 'GET /api/topic-map':
        await route.fulfill(json([
          {
            id: 1,
            title: 'Systems',
            description: null,
            concept_count: 3,
            avg_mastery: 54,
            due_count: 1,
            parent_ids: [],
            child_ids: [2],
          },
          {
            id: 2,
            title: 'Operating Systems',
            description: 'Scheduling and memory models.',
            concept_count: 2,
            avg_mastery: 51,
            due_count: 1,
            parent_ids: [1],
            child_ids: [3],
          },
          {
            id: 3,
            title: 'Processes',
            description: 'Lifecycle and isolation.',
            concept_count: 1,
            avg_mastery: 49,
            due_count: 0,
            parent_ids: [2],
            child_ids: [],
          },
        ]));
        return;
      case 'GET /api/topics/2':
        await route.fulfill(json({
          id: 2,
          title: 'Operating Systems',
          description: 'Scheduling and memory models.',
          concepts: [
            {
              id: 7,
              title: 'Process Scheduling',
              description: null,
              mastery_level: 58,
              review_count: 4,
              interval_days: 3,
              next_review_at: '2026-04-15 09:00:00',
              latest_remark: 'Round-robin vs. priority still needs work.',
            },
          ],
          children: [
            { id: 3, title: 'Processes', description: 'Lifecycle and isolation.' },
          ],
          parents: [
            { id: 1, title: 'Systems', description: null },
          ],
        }));
        return;
      default:
        await route.abort();
    }
  });

  await page.goto('/topics');

  await expect(page.getByRole('heading', { name: 'Topics' })).toBeVisible();

  const search = page.getByPlaceholder('Search topics...');
  await search.fill('Operating');

  await expect(page.getByText('1 match')).toBeVisible();
  await expect(page.getByRole('link', { name: 'Operating Systems' })).toBeVisible();

  await page.getByRole('link', { name: 'Operating Systems' }).click();

  await expect(page.getByRole('heading', { name: 'Topic Detail' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Operating Systems' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Systems' }).first()).toBeVisible();
  await expect(page.getByRole('link', { name: 'Process Scheduling' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Processes' })).toBeVisible();
});