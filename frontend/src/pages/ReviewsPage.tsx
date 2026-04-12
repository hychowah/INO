import { useQuery } from '@tanstack/react-query';
import { fetchReviews } from '../api';
import { AppLayout } from '../components/AppLayout';
import { resolveBackendHref } from '../lib/navigation';
import type { ReviewLogEntry } from '../types';

function qualityColor(quality?: number | null) {
  if (quality === 0 || quality === 1) {
    return 'var(--red)';
  }
  if (quality === 2) {
    return 'var(--orange)';
  }
  if (quality === 3) {
    return 'var(--yellow)';
  }
  if (quality === 4 || quality === 5) {
    return 'var(--green)';
  }
  return 'var(--text2)';
}

function reviewRowKey(review: ReviewLogEntry) {
  return review.id || `${review.concept_id}-${review.reviewed_at || 'review'}`;
}

export function ReviewsPage() {
  const reviewsQuery = useQuery<ReviewLogEntry[]>({
    queryKey: ['reviews', 50],
    queryFn: () => fetchReviews(50),
  });

  return (
    <AppLayout active="/reviews">
      <div className="chat-page">
        <div className="chat-shell">
          <div className="chat-header">
            <h2>Review Log</h2>
            <p className="chat-subtitle">Recent assessment history across all concepts.</p>
          </div>

          {reviewsQuery.isPending ? <div className="card">Loading reviews…</div> : null}
          {reviewsQuery.isError ? <div className="card chat-bubble-error">{(reviewsQuery.error as Error).message}</div> : null}

          {reviewsQuery.data ? <ReviewsTable reviews={reviewsQuery.data} /> : null}
        </div>
      </div>
    </AppLayout>
  );
}

function ReviewsTable({ reviews }: { reviews: ReviewLogEntry[] }) {
  if (!reviews.length) {
    return <div className="card">No reviews yet. Start learning and get quizzed!</div>;
  }

  return (
    <div className="card">
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Concept</th>
            <th>Question</th>
            <th>Answer</th>
            <th>Quality</th>
            <th>Assessment</th>
          </tr>
        </thead>
        <tbody>
          {reviews.map((review) => (
            <tr key={reviewRowKey(review)}>
              <td>{review.reviewed_at || '—'}</td>
              <td>
                <a href={resolveBackendHref(`/concept/${review.concept_id}`)}>{review.concept_title}</a>
              </td>
              <td style={{ maxWidth: '200px' }}>{review.question_asked || '—'}</td>
              <td style={{ maxWidth: '200px' }}>{review.user_response || '—'}</td>
              <td style={{ color: qualityColor(review.quality), fontWeight: 600, textAlign: 'center' }}>
                {review.quality ?? '?'} / 5
              </td>
              <td style={{ fontSize: '12px', color: 'var(--text2)' }}>{(review.llm_assessment || '').slice(0, 80)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}