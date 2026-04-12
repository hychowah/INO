import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { fetchReviews } from '../api';
import { AppLayout } from '../components/AppLayout';
import type { ReviewLogEntry } from '../types';

function qualityTone(quality?: number | null) {
  if (quality === 0 || quality === 1) {
    return 'border-red-500/30 bg-red-500/10 text-red-100';
  }
  if (quality === 2) {
    return 'border-orange-500/30 bg-orange-500/10 text-orange-100';
  }
  if (quality === 3) {
    return 'border-amber-500/30 bg-amber-500/10 text-amber-100';
  }
  if (quality === 4 || quality === 5) {
    return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100';
  }
  return 'border-white/10 bg-white/5 text-slate-300';
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
      <section className="space-y-6">
        <div className="flex flex-col gap-3">
          <Badge className="w-fit">Assessments</Badge>
          <div>
            <h2 className="text-3xl font-semibold tracking-tight text-white">Review Log</h2>
            <p className="mt-2 max-w-3xl text-sm text-slate-400">Recent assessment history across all concepts.</p>
          </div>
        </div>

        {reviewsQuery.isPending ? (
          <Card>
            <CardContent className="py-6 text-sm text-slate-300">Loading reviews…</CardContent>
          </Card>
        ) : null}

        {reviewsQuery.isError ? (
          <Card className="border-red-500/30 bg-red-500/10">
            <CardContent className="py-6 text-sm text-red-100">{(reviewsQuery.error as Error).message}</CardContent>
          </Card>
        ) : null}

        {reviewsQuery.data ? <ReviewsTable reviews={reviewsQuery.data} /> : null}
      </section>
    </AppLayout>
  );
}

function ReviewsTable({ reviews }: { reviews: ReviewLogEntry[] }) {
  if (!reviews.length) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-slate-300">No reviews yet. Start learning and get quizzed!</CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Recent Reviews</CardTitle>
        <CardDescription>Latest quiz and assessment outcomes across the knowledge base.</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full border-separate border-spacing-0 text-left text-sm text-slate-200">
            <thead>
              <tr className="text-xs uppercase tracking-[0.2em] text-slate-500">
                <th className="border-b border-white/10 px-4 py-3">Date</th>
                <th className="border-b border-white/10 px-4 py-3">Concept</th>
                <th className="border-b border-white/10 px-4 py-3">Question</th>
                <th className="border-b border-white/10 px-4 py-3">Answer</th>
                <th className="border-b border-white/10 px-4 py-3 text-center">Quality</th>
                <th className="border-b border-white/10 px-4 py-3">Assessment</th>
              </tr>
            </thead>
            <tbody>
              {reviews.map((review) => (
                <tr key={reviewRowKey(review)} className="align-top transition-colors hover:bg-white/5">
                  <td className="border-b border-white/5 px-4 py-3 text-slate-400">{review.reviewed_at || '—'}</td>
                  <td className="border-b border-white/5 px-4 py-3">
                    <Link className="font-medium text-sky-200 transition-colors hover:text-sky-100" to={`/concept/${review.concept_id}`}>{review.concept_title}</Link>
                  </td>
                  <td className="max-w-[200px] border-b border-white/5 px-4 py-3 text-slate-300">{review.question_asked || '—'}</td>
                  <td className="max-w-[200px] border-b border-white/5 px-4 py-3 text-slate-300">{review.user_response || '—'}</td>
                  <td className="border-b border-white/5 px-4 py-3 text-center">
                    <Badge className={qualityTone(review.quality)} variant="outline">{review.quality ?? '?'} / 5</Badge>
                  </td>
                  <td className="border-b border-white/5 px-4 py-3 text-xs text-slate-400">{(review.llm_assessment || '').slice(0, 80) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}