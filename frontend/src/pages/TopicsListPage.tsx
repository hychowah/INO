import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { fetchTopicMap } from '../api';
import { AppLayout } from '../components/AppLayout';
import type { TopicMapNode } from '../types';

const STORAGE_KEY = 'learning-react-topics-expanded';

function loadExpandedIds(topicMap: TopicMapNode[]) {
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Array<number | string>;
      return new Set(parsed.map((value) => Number(value)).filter((value) => Number.isInteger(value)));
    }
  } catch {
    // Ignore storage parsing issues and fall back to roots.
  }

  return new Set(topicMap.filter((topic) => !topic.parent_ids.length).map((topic) => topic.id));
}

function subtreeMatches(topicId: number, query: string, byId: Map<number, TopicMapNode>, memo: Map<number, boolean>): boolean {
  if (memo.has(topicId)) {
    return memo.get(topicId) || false;
  }

  const topic = byId.get(topicId);
  if (!topic) {
    memo.set(topicId, false);
    return false;
  }

  const ownMatch = topic.title.toLowerCase().includes(query);
  const childMatch = topic.child_ids.some((childId) => subtreeMatches(childId, query, byId, memo));
  const result = ownMatch || childMatch;
  memo.set(topicId, result);
  return result;
}

function TopicTreeNode({
  topic,
  byId,
  expandedIds,
  onToggle,
  query,
  matchMemo,
}: {
  topic: TopicMapNode;
  byId: Map<number, TopicMapNode>;
  expandedIds: Set<number>;
  onToggle: (topicId: number) => void;
  query: string;
  matchMemo: Map<number, boolean>;
}) {
  const children = topic.child_ids
    .map((childId) => byId.get(childId))
    .filter((child): child is TopicMapNode => Boolean(child))
    .sort((left, right) => left.title.localeCompare(right.title));
  const hasChildren = children.length > 0;
  const queryActive = Boolean(query);
  const visible = !queryActive || subtreeMatches(topic.id, query, byId, matchMemo);

  if (!visible) {
    return null;
  }

  const ownMatch = topic.title.toLowerCase().includes(query);
  const expanded = queryActive ? true : expandedIds.has(topic.id);

  return (
    <li className="space-y-3">
      <div className="flex flex-wrap items-center gap-3 text-sm text-slate-300">
        {hasChildren ? (
          <button
            type="button"
            className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-white/10 bg-white/5 text-slate-300 transition-colors hover:border-white/20 hover:bg-white/10 hover:text-white"
            onClick={() => onToggle(topic.id)}
            aria-label={expanded ? `Collapse ${topic.title}` : `Expand ${topic.title}`}
          >
            <span className={`transition-transform ${expanded ? 'rotate-90' : ''}`}>›</span>
          </button>
        ) : <span className="inline-flex h-7 w-7 items-center justify-center text-slate-600">•</span>}

        <Link className={`font-medium transition-colors hover:text-sky-100 ${ownMatch ? 'text-white' : 'text-sky-200'}`} to={`/topic/${topic.id}`}>{topic.title}</Link>
        <span className="text-slate-500">{topic.concept_count} concepts</span>
        <span className="text-slate-500">{topic.due_count} due</span>
        <span className="text-slate-500">avg {topic.avg_mastery}/100</span>
      </div>

      {hasChildren && expanded ? (
        <ul className="ml-6 space-y-3 border-l border-white/10 pl-4">
          {children.map((child) => (
            <TopicTreeNode
              key={child.id}
              topic={child}
              byId={byId}
              expandedIds={expandedIds}
              onToggle={onToggle}
              query={query}
              matchMemo={matchMemo}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function TopicsListPage() {
  const [query, setQuery] = useState('');
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const topicsQuery = useQuery<TopicMapNode[]>({
    queryKey: ['topics-list'],
    queryFn: async () => {
      const topicMap = await fetchTopicMap();
      setExpandedIds((current) => (current.size ? current : loadExpandedIds(topicMap)));
      return topicMap;
    },
  });

  function persistExpanded(next: Set<number>) {
    setExpandedIds(next);
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(Array.from(next)));
    } catch {
      // Ignore storage failures.
    }
  }

  function toggleTopic(topicId: number) {
    const next = new Set(expandedIds);
    if (next.has(topicId)) {
      next.delete(topicId);
    } else {
      next.add(topicId);
    }
    persistExpanded(next);
  }

  function expandAll(topicMap: TopicMapNode[]) {
    persistExpanded(new Set(topicMap.map((topic) => topic.id)));
  }

  function collapseAll(topicMap: TopicMapNode[]) {
    persistExpanded(new Set(topicMap.filter((topic) => !topic.parent_ids.length).map((topic) => topic.id)));
  }

  return (
    <AppLayout active="/topics">
      <section className="space-y-6">
        <div className="flex flex-col gap-3">
          <Badge className="w-fit">Topic Map</Badge>
          <div>
            <h2 className="text-3xl font-semibold tracking-tight text-white">Topics</h2>
            <p className="mt-2 max-w-3xl text-sm text-slate-400">Browse the topic hierarchy, inspect due counts, and navigate into migrated detail views.</p>
          </div>
        </div>

        {topicsQuery.isPending ? (
          <Card>
            <CardContent className="py-6 text-sm text-slate-300">Loading topics…</CardContent>
          </Card>
        ) : null}

        {topicsQuery.isError ? (
          <Card className="border-red-500/30 bg-red-500/10">
            <CardContent className="py-6 text-sm text-red-100">{(topicsQuery.error as Error).message}</CardContent>
          </Card>
        ) : null}

        {topicsQuery.data ? <TopicsContent topicMap={topicsQuery.data} query={query} onQueryChange={setQuery} expandedIds={expandedIds} onToggle={toggleTopic} onExpandAll={expandAll} onCollapseAll={collapseAll} /> : null}
      </section>
    </AppLayout>
  );
}

function TopicsContent({
  topicMap,
  query,
  onQueryChange,
  expandedIds,
  onToggle,
  onExpandAll,
  onCollapseAll,
}: {
  topicMap: TopicMapNode[];
  query: string;
  onQueryChange: (value: string) => void;
  expandedIds: Set<number>;
  onToggle: (topicId: number) => void;
  onExpandAll: (topicMap: TopicMapNode[]) => void;
  onCollapseAll: (topicMap: TopicMapNode[]) => void;
}) {
  const byId = useMemo(() => new Map(topicMap.map((topic) => [topic.id, topic])), [topicMap]);
  const roots = useMemo(
    () => topicMap.filter((topic) => !topic.parent_ids.length).sort((left, right) => left.title.localeCompare(right.title)),
    [topicMap]
  );
  const rootIds = new Set(roots.map((topic) => topic.id));
  const orphans = useMemo(
    () => topicMap.filter((topic) => !rootIds.has(topic.id) && topic.parent_ids.every((parentId) => !byId.has(parentId))).sort((left, right) => left.title.localeCompare(right.title)),
    [topicMap, rootIds, byId]
  );
  const normalizedQuery = query.trim().toLowerCase();
  const matchMemo = useMemo(() => new Map<number, boolean>(), [normalizedQuery, topicMap]);
  const matchCount = normalizedQuery
    ? topicMap.filter((topic) => topic.title.toLowerCase().includes(normalizedQuery)).length
    : 0;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Topic Explorer</CardTitle>
          <CardDescription>{topicMap.length} topics loaded. Search narrows the tree while keeping ancestor paths visible.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-1 flex-col gap-2 sm:flex-row sm:items-center">
              <input
                type="text"
                value={query}
                onChange={(event) => onQueryChange(event.target.value)}
                placeholder="Search topics..."
                className="h-11 w-full rounded-full border border-white/10 bg-slate-950/70 px-4 text-sm text-slate-100 outline-none transition focus:border-sky-400/50 focus:ring-2 focus:ring-sky-400/20 sm:max-w-md"
              />
              <span className="text-sm text-slate-500">{normalizedQuery ? `${matchCount} match${matchCount === 1 ? '' : 'es'}` : 'Type to filter the tree'}</span>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => onExpandAll(topicMap)}>Expand All</Button>
              <Button size="sm" variant="secondary" onClick={() => onCollapseAll(topicMap)}>Collapse All</Button>
            </div>
          </div>

          {topicMap.length ? (
            <div className="rounded-2xl border border-white/5 bg-slate-950/40 p-4">
              <ul className="space-y-3">
                {roots.map((topic) => (
                  <TopicTreeNode
                    key={topic.id}
                    topic={topic}
                    byId={byId}
                    expandedIds={expandedIds}
                    onToggle={onToggle}
                    query={normalizedQuery}
                    matchMemo={matchMemo}
                  />
                ))}
                {orphans.map((topic) => (
                  <TopicTreeNode
                    key={topic.id}
                    topic={topic}
                    byId={byId}
                    expandedIds={expandedIds}
                    onToggle={onToggle}
                    query={normalizedQuery}
                    matchMemo={matchMemo}
                  />
                ))}
              </ul>
            </div>
          ) : <p className="text-sm text-slate-400">No topics yet.</p>}
        </CardContent>
      </Card>
    </div>
  );
}