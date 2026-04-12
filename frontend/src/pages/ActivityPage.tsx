import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { fetchActionFilters, fetchActionLog } from '../api';
import { AppLayout } from '../components/AppLayout';
import type { ActionFilterOptions, ActionLogEntry, ActionLogResponse } from '../types';

const TIME_OPTIONS = [
  { value: 'today', label: 'Today' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: 'all', label: 'All time' },
] as const;

function actionLabel(action: string) {
  const labels: Record<string, string> = {
    add_concept: 'Added Concept',
    add_topic: 'Added Topic',
    update_concept: 'Updated Concept',
    update_topic: 'Updated Topic',
    delete_concept: 'Deleted Concept',
    delete_topic: 'Deleted Topic',
    link_concept: 'Linked Concept',
    unlink_concept: 'Unlinked Concept',
    link_topics: 'Linked Topics',
    assess: 'Assessment',
    quiz: 'Quiz Question',
    remark: 'Added Remark',
    suggest_topic: 'Suggested Topic',
    fetch: 'Data Fetch',
    list_topics: 'Listed Topics',
  };
  return labels[action] || action;
}

function summarizeEntry(entry: ActionLogEntry) {
  if (!entry.params) {
    return 'No parameters recorded';
  }

  try {
    const parsed = JSON.parse(entry.params) as Record<string, unknown>;
    const preview = Object.entries(parsed)
      .slice(0, 2)
      .map(([key, value]) => `${key}: ${String(value)}`)
      .join(' · ');
    return preview || 'No parameters recorded';
  } catch {
    return entry.params;
  }
}

function formatJsonish(value?: string | null) {
  if (!value) {
    return '—';
  }
  try {
    return JSON.stringify(JSON.parse(value), null, 2);
  } catch {
    return value;
  }
}

export function ActivityPage() {
  const [actionFilter, setActionFilter] = useState('');
  const [sourceFilter, setSourceFilter] = useState('');
  const [search, setSearch] = useState('');
  const [timeFilter, setTimeFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const filterOptionsQuery = useQuery<ActionFilterOptions>({
    queryKey: ['action-filters'],
    queryFn: fetchActionFilters,
  });

  const actionLogQuery = useQuery<ActionLogResponse>({
    queryKey: ['action-log', actionFilter, sourceFilter, search, timeFilter, page],
    queryFn: () => fetchActionLog({ action: actionFilter || undefined, source: sourceFilter || undefined, search: search || undefined, time: timeFilter, page, perPage: 20 }),
  });

  const totalPages = useMemo(() => {
    if (!actionLogQuery.data) {
      return 1;
    }
    return Math.max(1, Math.ceil(actionLogQuery.data.total / actionLogQuery.data.per_page));
  }, [actionLogQuery.data]);

  function updateFilters(callback: () => void) {
    callback();
    setPage(1);
    setExpandedId(null);
  }

  return (
    <AppLayout active="/actions">
      <section className="space-y-6">
        <div className="flex flex-col gap-3">
          <Badge className="w-fit">Audit Trail</Badge>
          <div>
            <h2 className="text-3xl font-semibold tracking-tight text-white">Activity Log</h2>
            <p className="mt-2 max-w-3xl text-sm text-slate-400">Filter action history by type, source, time range, and free-text search.</p>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Filters</CardTitle>
            <CardDescription>Server-backed filtering and pagination over the action log.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3 lg:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,0.7fr))]">
            <input
              type="text"
              value={search}
              onChange={(event) => updateFilters(() => setSearch(event.target.value))}
              placeholder="Search actions..."
              className="h-11 w-full rounded-full border border-white/10 bg-slate-950/70 px-4 text-sm text-slate-100 outline-none transition focus:border-sky-400/50 focus:ring-2 focus:ring-sky-400/20"
            />
            <select
              value={actionFilter}
              onChange={(event) => updateFilters(() => setActionFilter(event.target.value))}
              className="h-11 rounded-full border border-white/10 bg-slate-950/70 px-4 text-sm text-slate-100 outline-none transition focus:border-sky-400/50 focus:ring-2 focus:ring-sky-400/20"
            >
              <option value="">All Actions</option>
              {(filterOptionsQuery.data?.actions || []).map((action) => (
                <option key={action} value={action}>{actionLabel(action)}</option>
              ))}
            </select>
            <select
              value={sourceFilter}
              onChange={(event) => updateFilters(() => setSourceFilter(event.target.value))}
              className="h-11 rounded-full border border-white/10 bg-slate-950/70 px-4 text-sm text-slate-100 outline-none transition focus:border-sky-400/50 focus:ring-2 focus:ring-sky-400/20"
            >
              <option value="">All Sources</option>
              {(filterOptionsQuery.data?.sources || []).map((source) => (
                <option key={source} value={source}>{source}</option>
              ))}
            </select>
            <select
              value={timeFilter}
              onChange={(event) => updateFilters(() => setTimeFilter(event.target.value))}
              className="h-11 rounded-full border border-white/10 bg-slate-950/70 px-4 text-sm text-slate-100 outline-none transition focus:border-sky-400/50 focus:ring-2 focus:ring-sky-400/20"
            >
              {TIME_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </CardContent>
        </Card>

        {actionLogQuery.isPending ? (
          <Card>
            <CardContent className="py-6 text-sm text-slate-300">Loading activity…</CardContent>
          </Card>
        ) : null}

        {actionLogQuery.isError ? (
          <Card className="border-red-500/30 bg-red-500/10">
            <CardContent className="py-6 text-sm text-red-100">{(actionLogQuery.error as Error).message}</CardContent>
          </Card>
        ) : null}

        {actionLogQuery.data ? (
          <ActivityTable
            data={actionLogQuery.data}
            expandedId={expandedId}
            onToggleExpanded={(entryId) => setExpandedId((current) => (current === entryId ? null : entryId))}
            onPrevious={() => setPage((current) => Math.max(1, current - 1))}
            onNext={() => setPage((current) => Math.min(totalPages, current + 1))}
            totalPages={totalPages}
          />
        ) : null}
      </section>
    </AppLayout>
  );
}

function ActivityTable({
  data,
  expandedId,
  onToggleExpanded,
  onPrevious,
  onNext,
  totalPages,
}: {
  data: ActionLogResponse;
  expandedId: number | null;
  onToggleExpanded: (entryId: number) => void;
  onPrevious: () => void;
  onNext: () => void;
  totalPages: number;
}) {
  if (!data.items.length) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-slate-300">No actions logged for the current filters.</CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Entries</CardTitle>
        <CardDescription>{data.total} action{data.total === 1 ? '' : 's'} matched.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="overflow-x-auto">
          <table className="w-full border-separate border-spacing-0 text-left text-sm text-slate-200">
            <thead>
              <tr className="text-xs uppercase tracking-[0.2em] text-slate-500">
                <th className="border-b border-white/10 px-4 py-3">Time</th>
                <th className="border-b border-white/10 px-4 py-3">Source</th>
                <th className="border-b border-white/10 px-4 py-3">Action</th>
                <th className="border-b border-white/10 px-4 py-3">Summary</th>
                <th className="border-b border-white/10 px-4 py-3 text-center">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((entry) => (
                <FragmentRow key={entry.id} entry={entry} expanded={expandedId === entry.id} onToggleExpanded={() => onToggleExpanded(entry.id)} />
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between gap-3">
          <Button variant="secondary" disabled={data.page <= 1} onClick={onPrevious}>← Prev</Button>
          <span className="text-sm text-slate-500">Page {data.page} of {totalPages}</span>
          <Button variant="secondary" disabled={data.page >= totalPages} onClick={onNext}>Next →</Button>
        </div>
      </CardContent>
    </Card>
  );
}

function FragmentRow({ entry, expanded, onToggleExpanded }: { entry: ActionLogEntry; expanded: boolean; onToggleExpanded: () => void }) {
  return (
    <>
      <tr className="cursor-pointer transition-colors hover:bg-white/5" onClick={onToggleExpanded}>
        <td className="border-b border-white/5 px-4 py-3 text-slate-400">{entry.created_at || '—'}</td>
        <td className="border-b border-white/5 px-4 py-3"><Badge variant="outline">{entry.source || 'unknown'}</Badge></td>
        <td className="border-b border-white/5 px-4 py-3 font-medium text-slate-100">{actionLabel(entry.action)}</td>
        <td className="border-b border-white/5 px-4 py-3 text-slate-300">{summarizeEntry(entry)}</td>
        <td className="border-b border-white/5 px-4 py-3 text-center">
          <Badge className={entry.result_type === 'error' ? 'border-red-500/30 bg-red-500/10 text-red-100' : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100'} variant="outline">
            {entry.result_type === 'error' ? 'Error' : 'OK'}
          </Badge>
        </td>
      </tr>
      {expanded ? (
        <tr>
          <td className="bg-slate-950/30 px-4 py-4" colSpan={5}>
            <div className="grid gap-4 lg:grid-cols-2">
              <div>
                <div className="mb-2 text-xs uppercase tracking-[0.2em] text-slate-500">Params</div>
                <pre className="overflow-auto rounded-2xl border border-white/10 bg-slate-950/70 p-4 text-xs text-slate-300">{formatJsonish(entry.params)}</pre>
              </div>
              <div>
                <div className="mb-2 text-xs uppercase tracking-[0.2em] text-slate-500">Result</div>
                <pre className="overflow-auto rounded-2xl border border-white/10 bg-slate-950/70 p-4 text-xs text-slate-300">{formatJsonish(entry.result)}</pre>
              </div>
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}