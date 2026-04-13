import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { PageIntro } from '@/components/PageIntro';
import { fetchForecast, fetchForecastConcepts, fetchReviews } from '../api';
import { AppLayout } from '../components/AppLayout';
import type { ForecastBucket, ForecastConcept, ForecastSummary, ReviewLogEntry } from '../types';

type ForecastBar = ForecastBucket & {
  isOverdue?: boolean;
};

const RANGE_OPTIONS = [
  { value: 'days', label: '7 Days' },
  { value: 'weeks', label: '7 Weeks' },
  { value: 'months', label: '7 Months' },
] as const;

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
  return 'border-border bg-secondary/70 text-muted-foreground';
}

function reviewRowKey(review: ReviewLogEntry) {
  return review.id || `${review.concept_id}-${review.reviewed_at || 'review'}`;
}

function masteryTone(avgMastery: number) {
  if (avgMastery < 40) return 'bg-red-500/80';
  if (avgMastery < 70) return 'bg-amber-400/80';
  return 'bg-emerald-400/80';
}

export function ProgressPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const currentTab = location.pathname === '/forecast' || location.pathname === '/progress/forecast' ? 'forecast' : 'reviews';
  const [range, setRange] = useState<'days' | 'weeks' | 'months'>('weeks');
  const [selectedBucket, setSelectedBucket] = useState<string>('overdue');

  const reviewsQuery = useQuery<ReviewLogEntry[]>({
    queryKey: ['reviews', 50],
    queryFn: () => fetchReviews(50),
    enabled: currentTab === 'reviews',
  });

  const forecastQuery = useQuery<ForecastSummary>({
    queryKey: ['forecast', range],
    queryFn: () => fetchForecast(range),
    enabled: currentTab === 'forecast',
  });

  const bucketConceptsQuery = useQuery<ForecastConcept[]>({
    queryKey: ['forecast-concepts', range, selectedBucket],
    queryFn: () => fetchForecastConcepts(range, selectedBucket),
    enabled: currentTab === 'forecast' && Boolean(selectedBucket),
  });

  const bars = useMemo(() => {
    if (!forecastQuery.data) {
      return [] as ForecastBar[];
    }

    return [
      { label: 'Overdue', bucket_key: 'overdue', count: forecastQuery.data.overdue_count, avg_mastery: 0, isOverdue: true },
      ...forecastQuery.data.buckets.map((bucket) => ({ ...bucket, isOverdue: false })),
    ] as ForecastBar[];
  }, [forecastQuery.data]);

  function handleTabChange(nextTab: string) {
    navigate(nextTab === 'forecast' ? '/progress/forecast' : '/progress');
  }

  return (
    <AppLayout active={location.pathname}>
      <section className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-5">
        <PageIntro
          eyebrow="Progress"
          title="Review performance"
          description="Review history and upcoming load are now grouped into one shared surface instead of separate top-level pages."
          aside={
            <>
              <Badge variant="outline">Reviews + forecast</Badge>
              <Badge variant="muted">Legacy routes still supported</Badge>
            </>
          }
        />

        <Tabs value={currentTab} onValueChange={handleTabChange} className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-4">
          <TabsList>
            <TabsTrigger value="reviews">Reviews</TabsTrigger>
            <TabsTrigger value="forecast">Forecast</TabsTrigger>
          </TabsList>

          <TabsContent value="reviews" className="min-h-0">
            {reviewsQuery.isPending ? (
              <Card>
                <CardContent className="py-6 text-sm text-muted-foreground">Loading reviews…</CardContent>
              </Card>
            ) : null}

            {reviewsQuery.isError ? (
              <Card className="border-red-500/30 bg-red-500/10">
                <CardContent className="py-6 text-sm text-red-100">{(reviewsQuery.error as Error).message}</CardContent>
              </Card>
            ) : null}

            {reviewsQuery.data ? <ReviewsPanel reviews={reviewsQuery.data} /> : null}
          </TabsContent>

          <TabsContent value="forecast" className="min-h-0">
            <div className="grid min-h-0 gap-4 grid-rows-[auto_minmax(0,1fr)]">
              <Card>
                <CardHeader>
                  <CardTitle>Range</CardTitle>
                  <CardDescription>Switch between rolling day, week, and month windows.</CardDescription>
                </CardHeader>
                <CardContent className="flex flex-wrap gap-2">
                  {RANGE_OPTIONS.map((option) => (
                    <Button
                      key={option.value}
                      variant={range === option.value ? 'default' : 'secondary'}
                      size="sm"
                      onClick={() => {
                        setRange(option.value);
                        setSelectedBucket('overdue');
                      }}
                    >
                      {option.label}
                    </Button>
                  ))}
                </CardContent>
              </Card>

              {forecastQuery.isPending ? (
                <Card>
                  <CardContent className="py-6 text-sm text-muted-foreground">Loading forecast…</CardContent>
                </Card>
              ) : null}

              {forecastQuery.isError ? (
                <Card className="border-red-500/30 bg-red-500/10">
                  <CardContent className="py-6 text-sm text-red-100">{(forecastQuery.error as Error).message}</CardContent>
                </Card>
              ) : null}

              {forecastQuery.data ? (
                <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
                  <Card className="min-h-0 flex flex-col">
                    <CardHeader>
                      <CardTitle>Upcoming Review Buckets</CardTitle>
                      <CardDescription>Bucket height is proportional to due count. Color reflects average mastery.</CardDescription>
                    </CardHeader>
                    <CardContent className="min-h-0 flex-1">
                      <div className="app-scrollbar grid h-full gap-3 overflow-auto sm:grid-cols-2 xl:grid-cols-4">
                        {bars.map((bar) => (
                          <button
                            key={bar.bucket_key}
                            type="button"
                            onClick={() => setSelectedBucket(bar.bucket_key)}
                            className={`rounded-3xl border p-4 text-left transition-colors ${selectedBucket === bar.bucket_key ? 'border-primary/30 bg-primary/10' : 'border-border bg-background/35 hover:border-border/90 hover:bg-secondary/55'}`}
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div className="text-sm font-medium text-foreground">{bar.label}</div>
                              <Badge variant="outline">{bar.count}</Badge>
                            </div>
                            <div className="mt-4 h-28 rounded-2xl border border-border/60 bg-background/70 p-3">
                              <div className="flex h-full items-end">
                                <div className={`w-full rounded-xl ${bar.isOverdue ? (bar.count ? 'bg-red-500/80' : 'bg-muted') : bar.count ? masteryTone(bar.avg_mastery) : 'bg-muted'}`} style={{ height: `${Math.max(12, Math.min(100, bar.count * 12))}%` }} />
                              </div>
                            </div>
                            <div className="mt-3 text-xs text-muted-foreground">{bar.isOverdue ? 'Past due now' : `Avg mastery ${bar.avg_mastery}`}</div>
                          </button>
                        ))}
                      </div>
                    </CardContent>
                  </Card>

                  <Card className="min-h-0 flex flex-col">
                    <CardHeader>
                      <CardTitle>Bucket Detail</CardTitle>
                      <CardDescription>Concepts due in the selected bucket.</CardDescription>
                    </CardHeader>
                    <CardContent className="min-h-0 flex-1 space-y-3">
                      {bucketConceptsQuery.isPending ? <p className="text-sm text-muted-foreground">Loading concepts…</p> : null}
                      {bucketConceptsQuery.isError ? <p className="text-sm text-red-100">{(bucketConceptsQuery.error as Error).message}</p> : null}
                      {bucketConceptsQuery.data ? <ForecastConceptTable concepts={bucketConceptsQuery.data} /> : null}
                    </CardContent>
                  </Card>
                </div>
              ) : null}
            </div>
          </TabsContent>
        </Tabs>
      </section>
    </AppLayout>
  );
}

function ReviewsPanel({ reviews }: { reviews: ReviewLogEntry[] }) {
  if (!reviews.length) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-muted-foreground">No reviews yet. Start learning and get quizzed!</CardContent>
      </Card>
    );
  }

  return (
    <Card className="flex h-full min-h-0 flex-col">
      <CardHeader>
        <CardTitle>Recent Reviews</CardTitle>
        <CardDescription>Latest quiz and assessment outcomes across the knowledge base.</CardDescription>
      </CardHeader>
      <CardContent className="min-h-0 flex-1">
        <div className="app-scrollbar h-full overflow-auto">
          <table className="w-full border-separate border-spacing-0 text-left text-sm text-foreground">
            <thead>
              <tr className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                <th className="border-b border-border/80 px-4 py-3">Date</th>
                <th className="border-b border-border/80 px-4 py-3">Concept</th>
                <th className="border-b border-border/80 px-4 py-3">Question</th>
                <th className="border-b border-border/80 px-4 py-3">Answer</th>
                <th className="border-b border-border/80 px-4 py-3 text-center">Quality</th>
                <th className="border-b border-border/80 px-4 py-3">Assessment</th>
              </tr>
            </thead>
            <tbody>
              {reviews.map((review) => (
                <tr key={reviewRowKey(review)} className="align-top transition-colors hover:bg-secondary/50">
                  <td className="border-b border-border/40 px-4 py-3 text-muted-foreground">{review.reviewed_at || '—'}</td>
                  <td className="border-b border-border/40 px-4 py-3">
                    <Link className="font-medium text-primary transition-colors hover:text-primary/80" to={`/concept/${review.concept_id}`}>{review.concept_title}</Link>
                  </td>
                  <td className="max-w-[220px] border-b border-border/40 px-4 py-3 text-muted-foreground">{review.question_asked || '—'}</td>
                  <td className="max-w-[220px] border-b border-border/40 px-4 py-3 text-muted-foreground">{review.user_response || '—'}</td>
                  <td className="border-b border-border/40 px-4 py-3 text-center">
                    <Badge className={qualityTone(review.quality)} variant="outline">{review.quality ?? '?'} / 5</Badge>
                  </td>
                  <td className="border-b border-border/40 px-4 py-3 text-xs text-muted-foreground">{(review.llm_assessment || '').slice(0, 120) || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

function ForecastConceptTable({ concepts }: { concepts: ForecastConcept[] }) {
  if (!concepts.length) {
    return <p className="text-sm text-muted-foreground">No concepts in this bucket.</p>;
  }

  return (
    <div className="app-scrollbar h-full overflow-auto">
      <table className="w-full border-separate border-spacing-0 text-left text-sm text-foreground">
        <thead>
          <tr className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
            <th className="border-b border-border/80 px-3 py-3">Concept</th>
            <th className="border-b border-border/80 px-3 py-3">Mastery</th>
            <th className="border-b border-border/80 px-3 py-3">Next Review</th>
            <th className="border-b border-border/80 px-3 py-3">Interval</th>
          </tr>
        </thead>
        <tbody>
          {concepts.map((concept) => (
            <tr key={concept.id} className="transition-colors hover:bg-secondary/50">
              <td className="border-b border-border/40 px-3 py-3"><Link className="font-medium text-primary transition-colors hover:text-primary/80" to={`/concept/${concept.id}`}>{concept.title}</Link></td>
              <td className="border-b border-border/40 px-3 py-3">{concept.mastery_level}</td>
              <td className="border-b border-border/40 px-3 py-3 text-muted-foreground">{concept.next_review_at || '—'}</td>
              <td className="border-b border-border/40 px-3 py-3">{concept.interval_days != null ? `${concept.interval_days}d` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}