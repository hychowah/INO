import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { LoadingCard } from '@/components/LoadingCard';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { fetchTopicDetail, fetchTopicMap } from '../api';
import type { TopicDetail, TopicMapNode } from '../types';

type TopicDetailBundle = {
  topic: TopicDetail;
  topicMap: TopicMapNode[];
};

type TopicDetailViewProps = {
  topicId: number;
  showHeader?: boolean;
  embedded?: boolean;
  onSelectTopic?: (topicId: number) => void;
};

function buildAncestorTrail(topicId: number, byId: Map<number, TopicMapNode>) {
  const trail: TopicMapNode[] = [];
  const seen = new Set<number>();
  let current = byId.get(topicId);

  while (current && current.parent_ids.length) {
    const parentId = current.parent_ids[0];
    if (seen.has(parentId)) {
      break;
    }
    const parent = byId.get(parentId);
    if (!parent) {
      break;
    }
    trail.unshift(parent);
    seen.add(parentId);
    current = parent;
  }

  return trail;
}

export function TopicDetailPage() {
  const params = useParams<{ topicId: string }>();
  const topicId = Number(params.topicId);

  return <TopicDetailView topicId={topicId} />;
}

export function TopicDetailView({ topicId, showHeader = true, embedded = false, onSelectTopic }: TopicDetailViewProps) {
  const isValidTopicId = Number.isInteger(topicId) && topicId > 0;

  const topicQuery = useQuery<TopicDetailBundle>({
    queryKey: ['topic-detail', topicId],
    enabled: isValidTopicId,
    queryFn: async () => {
      const [topic, topicMap] = await Promise.all([
        fetchTopicDetail(topicId),
        fetchTopicMap(),
      ]);
      return { topic, topicMap };
    },
  });

  return (
    <section className="space-y-6">
        {showHeader ? (
          <div className="flex flex-col gap-3">
            <Badge className="w-fit">Topic</Badge>
            <div>
              <h2 className="text-3xl font-semibold tracking-tight text-white">Topic Detail</h2>
              <p className="mt-2 max-w-3xl text-sm text-slate-400">Topic hierarchy, linked concepts, and immediate neighbors in the graph.</p>
            </div>
          </div>
        ) : null}

        {!isValidTopicId ? (
          <Card className="border-red-500/30 bg-red-500/10">
            <CardContent className="py-6 text-sm text-red-100">Invalid topic id.</CardContent>
          </Card>
        ) : null}

        {topicQuery.isPending ? <LoadingCard label="Loading topic…" rows={3} /> : null}

        {topicQuery.isError ? (
          <Card className="border-red-500/30 bg-red-500/10">
            <CardContent className="py-6 text-sm text-red-100">{(topicQuery.error as Error).message}</CardContent>
          </Card>
        ) : null}

        {topicQuery.data ? (
          <TopicDetailContent
            topic={topicQuery.data.topic}
            topicMap={topicQuery.data.topicMap}
            embedded={embedded}
            onSelectTopic={onSelectTopic}
          />
        ) : null}
      </section>
  );
}

function TopicDetailContent({ topic, topicMap, embedded = false, onSelectTopic }: TopicDetailBundle & Pick<TopicDetailViewProps, 'embedded' | 'onSelectTopic'>) {
  const byId = new Map(topicMap.map((item) => [item.id, item]));
  const trail = buildAncestorTrail(topic.id, byId);

  function renderTopicLink(topicId: number, title: string, className: string) {
    if (onSelectTopic) {
      return (
        <button type="button" className={className} onClick={() => onSelectTopic(topicId)}>
          {title}
        </button>
      );
    }

    return <Link className={className} to={`/topic/${topicId}`}>{title}</Link>;
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2 text-sm text-slate-400">
            {embedded ? (
              <span className="text-slate-300">Topics</span>
            ) : (
              <Link className="transition-colors hover:text-slate-200" to="/topics">Topics</Link>
            )}
            {trail.map((ancestor) => (
              <span key={ancestor.id} className="flex items-center gap-2">
                <span>/</span>
                {renderTopicLink(ancestor.id, ancestor.title, 'transition-colors hover:text-slate-200')}
              </span>
            ))}
            <span className="flex items-center gap-2 text-slate-200">
              <span>/</span>
              <span>{topic.title}</span>
            </span>
          </div>
          <CardTitle className="text-2xl">{topic.title}</CardTitle>
          <CardDescription>{topic.description || 'No description for this topic yet.'}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Badge>{topic.concepts.length} linked concepts</Badge>
          <Badge variant="outline">{topic.children.length} child topics</Badge>
          <Badge variant="outline">{topic.parents.length} parent topics</Badge>
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,0.9fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Concepts</CardTitle>
            <CardDescription>Concepts currently linked to this topic.</CardDescription>
          </CardHeader>
          <CardContent>
            {topic.concepts.length ? (
              <div className="overflow-x-auto">
                <Table className="text-slate-200">
                  <TableHeader>
                    <TableRow className="text-slate-500">
                      <TableHead className="border-b border-white/10">Concept</TableHead>
                      <TableHead className="border-b border-white/10">Score</TableHead>
                      <TableHead className="border-b border-white/10">Reviews</TableHead>
                      <TableHead className="border-b border-white/10">Next Review</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {topic.concepts.map((concept) => (
                      <TableRow key={concept.id} className="hover:bg-white/5">
                        <TableCell className="border-b border-white/5">
                          <Link className="font-medium text-sky-200 transition-colors hover:text-sky-100" to={`/concept/${concept.id}`}>{concept.title}</Link>
                          {concept.latest_remark ? <div className="mt-1 text-xs text-slate-500">{concept.latest_remark}</div> : null}
                        </TableCell>
                        <TableCell className="border-b border-white/5">{concept.mastery_level}/100</TableCell>
                        <TableCell className="border-b border-white/5">{concept.review_count}</TableCell>
                        <TableCell className="border-b border-white/5 text-slate-400">{concept.next_review_at || '—'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : <p className="text-sm text-slate-400">No concepts linked to this topic yet.</p>}
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Parent Topics</CardTitle>
              <CardDescription>Immediate parent relationships for this topic.</CardDescription>
            </CardHeader>
            <CardContent>
              {topic.parents.length ? (
                <div className="flex flex-wrap gap-2">
                  {topic.parents.map((parent) => (
                    <span key={parent.id}>
                      {renderTopicLink(parent.id, parent.title, 'inline-flex rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 transition-colors hover:border-white/20 hover:bg-white/10')}
                    </span>
                  ))}
                </div>
              ) : <p className="text-sm text-slate-400">No parent topics.</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Child Topics</CardTitle>
              <CardDescription>Immediate children of this topic.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {topic.children.length ? topic.children.map((child) => {
                const childStats = byId.get(child.id);
                return (
                  <div key={child.id} className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                    {renderTopicLink(child.id, child.title, 'font-medium text-sky-200 transition-colors hover:text-sky-100')}
                    {child.description ? <p className="mt-2 text-sm text-slate-400">{child.description}</p> : null}
                    {childStats ? <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-500"><span>{childStats.concept_count} concepts</span><span>{childStats.due_count} due</span></div> : null}
                  </div>
                );
              }) : <p className="text-sm text-slate-400">No child topics.</p>}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}