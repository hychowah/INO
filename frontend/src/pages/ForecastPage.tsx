import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { fetchForecast, fetchForecastConcepts } from '../api';
import { AppLayout } from '../components/AppLayout';
import type { ForecastBucket, ForecastConcept, ForecastSummary } from '../types';

type ForecastBar = ForecastBucket & {
  isOverdue?: boolean;
};

const RANGE_OPTIONS = [
  { value: 'days', label: '7 Days' },
  { value: 'weeks', label: '7 Weeks' },
  { value: 'months', label: '7 Months' },
] as const;

function masteryTone(avgMastery: number) {
  if (avgMastery < 40) return 'bg-red-500/80';
  if (avgMastery < 70) return 'bg-amber-400/80';
  return 'bg-emerald-400/80';
}

export function ForecastPage() {
  const [range, setRange] = useState<'days' | 'weeks' | 'months'>('weeks');
  const [selectedBucket, setSelectedBucket] = useState<string>('overdue');

  const forecastQuery = useQuery<ForecastSummary>({
    queryKey: ['forecast', range],
    queryFn: () => fetchForecast(range),
  });

  const bucketConceptsQuery = useQuery<ForecastConcept[]>({
    queryKey: ['forecast-concepts', range, selectedBucket],
    queryFn: () => fetchForecastConcepts(range, selectedBucket),
    enabled: Boolean(selectedBucket),
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

  return (
    <AppLayout active="/forecast">
      <section className="space-y-6">
        <div className="flex flex-col gap-3">
          <Badge className="w-fit">Review Load</Badge>
          <div>
            <h2 className="text-3xl font-semibold tracking-tight text-white">Forecast</h2>
            <p className="mt-2 max-w-3xl text-sm text-slate-400">Review demand over upcoming windows. Click a bucket to inspect the underlying concepts.</p>
          </div>
        </div>

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
            <CardContent className="py-6 text-sm text-slate-300">Loading forecast…</CardContent>
          </Card>
        ) : null}

        {forecastQuery.isError ? (
          <Card className="border-red-500/30 bg-red-500/10">
            <CardContent className="py-6 text-sm text-red-100">{(forecastQuery.error as Error).message}</CardContent>
          </Card>
        ) : null}

        {forecastQuery.data ? (
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_340px]">
            <Card>
              <CardHeader>
                <CardTitle>Upcoming Review Buckets</CardTitle>
                <CardDescription>Bucket height is proportional to due count. Color reflects average mastery.</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {bars.map((bar) => (
                    <button
                      key={bar.bucket_key}
                      type="button"
                      onClick={() => setSelectedBucket(bar.bucket_key)}
                      className={`rounded-3xl border p-4 text-left transition-colors ${selectedBucket === bar.bucket_key ? 'border-sky-400/40 bg-sky-400/10' : 'border-white/10 bg-slate-950/40 hover:border-white/20 hover:bg-white/5'}`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-medium text-slate-100">{bar.label}</div>
                        <Badge variant="outline">{bar.count}</Badge>
                      </div>
                      <div className="mt-4 h-28 rounded-2xl border border-white/5 bg-slate-950/70 p-3">
                        <div className="flex h-full items-end">
                          <div className={`w-full rounded-xl ${bar.isOverdue ? (bar.count ? 'bg-red-500/80' : 'bg-slate-600') : bar.count ? masteryTone(bar.avg_mastery) : 'bg-slate-600'}`} style={{ height: `${Math.max(12, Math.min(100, bar.count * 12))}%` }} />
                        </div>
                      </div>
                      <div className="mt-3 text-xs text-slate-500">{bar.isOverdue ? 'Past due now' : `Avg mastery ${bar.avg_mastery}`}</div>
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Bucket Detail</CardTitle>
                <CardDescription>Concepts due in the selected bucket.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {bucketConceptsQuery.isPending ? <p className="text-sm text-slate-300">Loading concepts…</p> : null}
                {bucketConceptsQuery.isError ? <p className="text-sm text-red-100">{(bucketConceptsQuery.error as Error).message}</p> : null}
                {bucketConceptsQuery.data ? <ForecastConceptTable concepts={bucketConceptsQuery.data} /> : null}
              </CardContent>
            </Card>
          </div>
        ) : null}
      </section>
    </AppLayout>
  );
}

function ForecastConceptTable({ concepts }: { concepts: ForecastConcept[] }) {
  if (!concepts.length) {
    return <p className="text-sm text-slate-400">No concepts in this bucket.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-0 text-left text-sm text-slate-200">
        <thead>
          <tr className="text-xs uppercase tracking-[0.2em] text-slate-500">
            <th className="border-b border-white/10 px-3 py-3">Concept</th>
            <th className="border-b border-white/10 px-3 py-3">Mastery</th>
            <th className="border-b border-white/10 px-3 py-3">Next Review</th>
            <th className="border-b border-white/10 px-3 py-3">Interval</th>
          </tr>
        </thead>
        <tbody>
          {concepts.map((concept) => (
            <tr key={concept.id} className="transition-colors hover:bg-white/5">
              <td className="border-b border-white/5 px-3 py-3"><Link className="font-medium text-sky-200 transition-colors hover:text-sky-100" to={`/concept/${concept.id}`}>{concept.title}</Link></td>
              <td className="border-b border-white/5 px-3 py-3">{concept.mastery_level}</td>
              <td className="border-b border-white/5 px-3 py-3 text-slate-400">{concept.next_review_at || '—'}</td>
              <td className="border-b border-white/5 px-3 py-3">{concept.interval_days != null ? `${concept.interval_days}d` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}