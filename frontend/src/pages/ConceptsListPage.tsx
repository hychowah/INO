import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { deleteConcept, fetchConcepts, fetchTopicsFlat } from '../api';
import { AppLayout } from '../components/AppLayout';
import type {
  ConceptListItem,
  ConceptListResponse,
  ConceptListSortField,
  ConceptListStatus,
  TopicSummary,
} from '../types';

const STORAGE_KEY = 'learning-react-concepts-state';
const PAGE_SIZE = 20;

const STATUS_OPTIONS: Array<{ value: ConceptListStatus; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'due', label: 'Due' },
  { value: 'upcoming', label: 'Upcoming' },
  { value: 'never', label: 'New' },
];

const SORT_LABELS: Record<ConceptListSortField, string> = {
  id: 'ID',
  title: 'Concept',
  mastery_level: 'Score',
  interval_days: 'Interval',
  review_count: 'Reviews',
  next_review_at: 'Next Review',
  last_reviewed_at: 'Last Review',
};

const DEFAULT_SORT_ORDER: Record<ConceptListSortField, 'asc' | 'desc'> = {
  id: 'asc',
  title: 'asc',
  mastery_level: 'desc',
  interval_days: 'desc',
  review_count: 'desc',
  next_review_at: 'asc',
  last_reviewed_at: 'desc',
};

type ConceptsState = {
  search: string;
  topicId: string;
  status: ConceptListStatus;
  sort: ConceptListSortField;
  order: 'asc' | 'desc';
  page: number;
};

function loadState(): ConceptsState {
  const fallback: ConceptsState = {
    search: '',
    topicId: '',
    status: 'all',
    sort: 'next_review_at',
    order: 'asc',
    page: 1,
  };

  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return fallback;
    }

    const parsed = JSON.parse(raw) as Partial<ConceptsState>;
    return {
      ...fallback,
      ...parsed,
      page: typeof parsed.page === 'number' && parsed.page > 0 ? parsed.page : 1,
    };
  } catch {
    return fallback;
  }
}

function formatFutureRelative(dateStr?: string | null) {
  if (!dateStr) {
    return '—';
  }

  const parsed = new Date(dateStr.replace(' ', 'T'));
  if (Number.isNaN(parsed.getTime())) {
    return dateStr;
  }

  const now = new Date();
  const diffDays = Math.round((parsed.getTime() - now.getTime()) / 86400000);
  if (diffDays < 0) {
    return `Overdue ${Math.abs(diffDays)}d`;
  }
  if (diffDays === 0) {
    return 'Today';
  }
  if (diffDays === 1) {
    return 'Tomorrow';
  }
  if (diffDays <= 30) {
    return `in ${diffDays}d`;
  }
  return `in ~${Math.round(diffDays / 30)}mo`;
}

function formatPastRelative(dateStr?: string | null) {
  if (!dateStr) {
    return '—';
  }

  const parsed = new Date(dateStr.replace(' ', 'T'));
  if (Number.isNaN(parsed.getTime())) {
    return dateStr;
  }

  const now = new Date();
  const diffDays = Math.round((now.getTime() - parsed.getTime()) / 86400000);
  if (diffDays <= 0) {
    return 'Today';
  }
  if (diffDays === 1) {
    return 'Yesterday';
  }
  if (diffDays <= 30) {
    return `${diffDays}d ago`;
  }
  return `~${Math.round(diffDays / 30)}mo ago`;
}

function previewRemark(remark?: string | null) {
  if (!remark) {
    return null;
  }
  return remark.length > 70 ? `${remark.slice(0, 70)}…` : remark;
}

function scoreTone(score: number) {
  if (score >= 75) {
    return 'bg-emerald-400';
  }
  if (score >= 50) {
    return 'bg-sky-400';
  }
  if (score >= 25) {
    return 'bg-amber-400';
  }
  return 'bg-rose-400';
}

export function ConceptsListPage() {
  const [state, setState] = useState<ConceptsState>(() => loadState());
  const [pendingDelete, setPendingDelete] = useState<ConceptListItem | null>(null);
  const deferredSearch = useDeferredValue(state.search.trim());
  const queryClient = useQueryClient();

  useEffect(() => {
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // Ignore storage failures.
    }
  }, [state]);

  const topicsQuery = useQuery<TopicSummary[]>({
    queryKey: ['topics-flat'],
    queryFn: fetchTopicsFlat,
  });

  const conceptsQuery = useQuery<ConceptListResponse>({
    queryKey: ['concepts-list', deferredSearch, state.topicId, state.status, state.sort, state.order, state.page],
    queryFn: () => fetchConcepts({
      search: deferredSearch || undefined,
      topicId: state.topicId ? Number(state.topicId) : undefined,
      status: state.status,
      sort: state.sort,
      order: state.order,
      page: state.page,
      perPage: PAGE_SIZE,
    }),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteConcept,
    onSuccess: async () => {
      setPendingDelete(null);
      await queryClient.invalidateQueries({ queryKey: ['concepts-list'] });
    },
  });

  const totalPages = useMemo(() => {
    if (!conceptsQuery.data) {
      return 1;
    }
    return Math.max(1, Math.ceil(conceptsQuery.data.total / conceptsQuery.data.per_page));
  }, [conceptsQuery.data]);

  function updateState(patch: Partial<ConceptsState>, resetPage = true) {
    setState((current) => ({
      ...current,
      ...patch,
      page: resetPage ? 1 : patch.page ?? current.page,
    }));
  }

  function toggleSort(field: ConceptListSortField) {
    setState((current) => {
      if (current.sort === field) {
        return {
          ...current,
          order: current.order === 'asc' ? 'desc' : 'asc',
          page: 1,
        };
      }
      return {
        ...current,
        sort: field,
        order: DEFAULT_SORT_ORDER[field],
        page: 1,
      };
    });
  }

  function emptyMessage() {
    if (state.status === 'never') {
      return 'No new concepts. Everything in scope has been reviewed at least once.';
    }
    if (deferredSearch || state.topicId || state.status !== 'all') {
      return 'No concepts matched the current filters.';
    }
    return 'No concepts yet.';
  }

  return (
    <AppLayout active="/concepts">
      <section className="space-y-6">
        <div className="flex flex-col gap-3">
          <Badge className="w-fit">Knowledge Base</Badge>
          <div>
            <h2 className="text-3xl font-semibold tracking-tight text-white">Concepts</h2>
            <p className="mt-2 max-w-3xl text-sm text-slate-400">Search, filter, sort, and prune concepts without leaving the migrated React surface.</p>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Filters</CardTitle>
            <CardDescription>Server-backed search, status filtering, and sort order with pagination.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1.4fr)_repeat(3,minmax(0,0.7fr))]">
              <input
                type="text"
                value={state.search}
                onChange={(event) => updateState({ search: event.target.value })}
                placeholder="Search concepts, topics, or remarks..."
                className="h-11 w-full rounded-full border border-white/10 bg-slate-950/70 px-4 text-sm text-slate-100 outline-none transition focus:border-sky-400/50 focus:ring-2 focus:ring-sky-400/20"
              />
              <select
                value={state.topicId}
                onChange={(event) => updateState({ topicId: event.target.value })}
                className="h-11 rounded-full border border-white/10 bg-slate-950/70 px-4 text-sm text-slate-100 outline-none transition focus:border-sky-400/50 focus:ring-2 focus:ring-sky-400/20"
              >
                <option value="">All Topics</option>
                {(topicsQuery.data || []).map((topic) => (
                  <option key={topic.id} value={topic.id}>{topic.title}</option>
                ))}
              </select>
              <select
                value={state.sort}
                onChange={(event) => updateState({ sort: event.target.value as ConceptListSortField, order: DEFAULT_SORT_ORDER[event.target.value as ConceptListSortField] })}
                className="h-11 rounded-full border border-white/10 bg-slate-950/70 px-4 text-sm text-slate-100 outline-none transition focus:border-sky-400/50 focus:ring-2 focus:ring-sky-400/20"
              >
                {Object.entries(SORT_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
              <select
                value={state.order}
                onChange={(event) => updateState({ order: event.target.value as 'asc' | 'desc' })}
                className="h-11 rounded-full border border-white/10 bg-slate-950/70 px-4 text-sm text-slate-100 outline-none transition focus:border-sky-400/50 focus:ring-2 focus:ring-sky-400/20"
              >
                <option value="asc">Ascending</option>
                <option value="desc">Descending</option>
              </select>
            </div>

            <div className="flex flex-wrap gap-2">
              {STATUS_OPTIONS.map((option) => (
                <Button
                  key={option.value}
                  type="button"
                  size="sm"
                  variant={state.status === option.value ? 'default' : 'secondary'}
                  onClick={() => updateState({ status: option.value })}
                >
                  {option.label}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>

        {conceptsQuery.isPending ? (
          <Card>
            <CardContent className="py-6 text-sm text-slate-300">Loading concepts…</CardContent>
          </Card>
        ) : null}

        {conceptsQuery.isError ? (
          <Card className="border-red-500/30 bg-red-500/10">
            <CardContent className="py-6 text-sm text-red-100">{(conceptsQuery.error as Error).message}</CardContent>
          </Card>
        ) : null}

        {conceptsQuery.data ? (
          <ConceptsTable
            data={conceptsQuery.data}
            currentState={state}
            totalPages={totalPages}
            onPageChange={(page) => updateState({ page }, false)}
            onSort={toggleSort}
            onTopicFilter={(topicId) => updateState({ topicId: String(topicId) })}
            onDelete={setPendingDelete}
            emptyMessage={emptyMessage()}
          />
        ) : null}
      </section>

      {pendingDelete ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 px-4 backdrop-blur-sm">
          <Card className="w-full max-w-lg border-red-500/30 bg-slate-950/95">
            <CardHeader>
              <CardTitle>Delete Concept</CardTitle>
              <CardDescription>This permanently removes the concept, its remarks, relations, and review history.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-slate-200">
                <div className="font-medium text-white">{pendingDelete.title}</div>
                <div className="mt-2 text-slate-400">{pendingDelete.review_count} review{pendingDelete.review_count === 1 ? '' : 's'} recorded</div>
              </div>
              {deleteMutation.isError ? (
                <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-100">{(deleteMutation.error as Error).message}</div>
              ) : null}
              <div className="flex justify-end gap-2">
                <Button type="button" variant="secondary" onClick={() => setPendingDelete(null)} disabled={deleteMutation.isPending}>Cancel</Button>
                <Button
                  type="button"
                  className="bg-red-500 text-white hover:bg-red-400"
                  onClick={() => deleteMutation.mutate(pendingDelete.id)}
                  disabled={deleteMutation.isPending}
                >
                  {deleteMutation.isPending ? 'Deleting…' : 'Delete'}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </AppLayout>
  );
}

function ConceptsTable({
  data,
  currentState,
  totalPages,
  onPageChange,
  onSort,
  onTopicFilter,
  onDelete,
  emptyMessage,
}: {
  data: ConceptListResponse;
  currentState: ConceptsState;
  totalPages: number;
  onPageChange: (page: number) => void;
  onSort: (field: ConceptListSortField) => void;
  onTopicFilter: (topicId: number) => void;
  onDelete: (concept: ConceptListItem) => void;
  emptyMessage: string;
}) {
  if (!data.items.length) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-slate-300">{emptyMessage}</CardContent>
      </Card>
    );
  }

  const countLabel = data.total === 1 ? '1 concept' : `${data.total} concepts`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Catalog</CardTitle>
        <CardDescription>{countLabel} matched. Page {data.page} of {totalPages}.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="overflow-x-auto">
          <table className="w-full border-separate border-spacing-0 text-left text-sm text-slate-200">
            <thead>
              <tr className="text-xs uppercase tracking-[0.2em] text-slate-500">
                {(['id', 'title', 'mastery_level', 'interval_days', 'review_count', 'next_review_at', 'last_reviewed_at'] as ConceptListSortField[]).map((field) => (
                  <th key={field} className="border-b border-white/10 px-4 py-3">
                    <button
                      type="button"
                      className="inline-flex items-center gap-2 text-left transition-colors hover:text-slate-200"
                      onClick={() => onSort(field)}
                    >
                      <span>{SORT_LABELS[field]}</span>
                      {currentState.sort === field ? <span>{currentState.order === 'asc' ? '↑' : '↓'}</span> : null}
                    </button>
                  </th>
                ))}
                <th className="border-b border-white/10 px-4 py-3">Topics</th>
                <th className="border-b border-white/10 px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((concept) => (
                <tr key={concept.id} className="transition-colors hover:bg-white/5">
                  <td className="border-b border-white/5 px-4 py-3 text-slate-400">#{concept.id}</td>
                  <td className="border-b border-white/5 px-4 py-3">
                    <Link className="font-medium text-sky-200 transition-colors hover:text-sky-100" to={`/concept/${concept.id}`}>{concept.title}</Link>
                    {previewRemark(concept.latest_remark) ? <div className="mt-1 text-xs text-slate-500">{previewRemark(concept.latest_remark)}</div> : null}
                  </td>
                  <td className="border-b border-white/5 px-4 py-3">
                    <div className="flex min-w-28 items-center gap-3">
                      <div className="h-2 flex-1 overflow-hidden rounded-full bg-white/10">
                        <div className={`h-full rounded-full ${scoreTone(concept.mastery_level)}`} style={{ width: `${concept.mastery_level}%` }} />
                      </div>
                      <span>{concept.mastery_level}</span>
                    </div>
                  </td>
                  <td className="border-b border-white/5 px-4 py-3 text-slate-300">{concept.review_count > 0 ? `${concept.interval_days || 1}d` : '—'}</td>
                  <td className="border-b border-white/5 px-4 py-3 text-slate-300">{concept.review_count}</td>
                  <td className="border-b border-white/5 px-4 py-3 text-slate-300">{formatFutureRelative(concept.next_review_at)}</td>
                  <td className="border-b border-white/5 px-4 py-3 text-slate-300">{formatPastRelative(concept.last_reviewed_at)}</td>
                  <td className="border-b border-white/5 px-4 py-3">
                    <div className="flex flex-wrap gap-2">
                      {concept.topics.length ? concept.topics.map((topic) => (
                        <button
                          key={topic.id}
                          type="button"
                          className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-200 transition-colors hover:border-white/20 hover:bg-white/10"
                          onClick={() => onTopicFilter(topic.id)}
                        >
                          {topic.title}
                        </button>
                      )) : <span className="text-slate-500">untagged</span>}
                    </div>
                  </td>
                  <td className="border-b border-white/5 px-4 py-3 text-right">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      className="border-red-500/30 text-red-100 hover:bg-red-500/10"
                      onClick={() => onDelete(concept)}
                    >
                      Delete
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between gap-3">
          <Button variant="secondary" disabled={data.page <= 1} onClick={() => onPageChange(Math.max(1, data.page - 1))}>← Prev</Button>
          <span className="text-sm text-slate-500">Page {data.page} of {totalPages}</span>
          <Button variant="secondary" disabled={data.page >= totalPages} onClick={() => onPageChange(Math.min(totalPages, data.page + 1))}>Next →</Button>
        </div>
      </CardContent>
    </Card>
  );
}