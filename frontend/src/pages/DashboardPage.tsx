import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { PageIntro } from '@/components/PageIntro';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { AppLayout } from '../components/AppLayout';
import { fetchActionSummary, fetchDueConcepts, fetchReviewStats, fetchTopicMap } from '../api';
import type { ActionSummary, DueConcept, ReviewStats, TopicMapNode } from '../types';

type DashboardBundle = {
  stats: ReviewStats;
  dueConcepts: DueConcept[];
  actionSummary: ActionSummary;
  topicMap: TopicMapNode[];
};

function summarizeActivity(actions: Record<string, number>) {
  const parts: string[] = [];
  for (const [key, label] of [
    ['assess', 'reviews'],
    ['add_concept', 'concepts added'],
    ['add_topic', 'topics created'],
    ['quiz', 'quizzes'],
  ] as const) {
    if (actions[key]) {
      parts.push(`${actions[key]} ${label}`);
    }
  }
  return parts.length ? parts.join(', ') : 'no activity';
}

function TopicTree({ node, byId, seen }: { node: TopicMapNode; byId: Map<number, TopicMapNode>; seen: Set<number> }) {
  if (seen.has(node.id)) {
    return null;
  }
  seen.add(node.id);
  const children = node.child_ids
    .map((childId) => byId.get(childId))
    .filter((child): child is TopicMapNode => Boolean(child))
    .sort((left, right) => left.title.localeCompare(right.title));

  return (
    <li className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm text-slate-300">
        <Link className="font-medium text-sky-200 transition-colors hover:text-sky-100" to={`/topic/${node.id}`}>{node.title}</Link>
        <span className="text-slate-500">{node.concept_count} concepts</span>
        <span className="text-slate-500">{node.due_count} due</span>
      </div>
      {children.length ? (
        <ul className="ml-4 space-y-3 border-l border-white/10 pl-4">
          {children.map((child) => (
            <TopicTree key={child.id} node={child} byId={byId} seen={seen} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function DashboardPage() {
  const dashboardQuery = useQuery<DashboardBundle>({
    queryKey: ['dashboard'],
    queryFn: async () => {
      const [stats, dueConcepts, actionSummary, topicMap] = await Promise.all([
        fetchReviewStats(),
        fetchDueConcepts(10),
        fetchActionSummary(7),
        fetchTopicMap(),
      ]);
      return { stats, dueConcepts, actionSummary, topicMap };
    },
  });

  return (
    <AppLayout active="/">
      <section className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-5">
        <PageIntro
          eyebrow="Overview"
          title="Dashboard"
          description="A compact operational view of due work, knowledge coverage, and recent movement across the learning system."
          aside={
            <>
              <Badge variant="outline">Due + activity</Badge>
              <Badge variant="muted">Desktop panel layout</Badge>
            </>
          }
        />

        {dashboardQuery.isPending ? (
          <Card>
            <CardContent className="py-6 text-sm text-muted-foreground">Loading dashboard…</CardContent>
          </Card>
        ) : null}

        {dashboardQuery.isError ? (
          <Card className="border-red-500/30 bg-red-500/10">
            <CardContent className="py-6 text-sm text-red-100">{(dashboardQuery.error as Error).message}</CardContent>
          </Card>
        ) : null}

        {dashboardQuery.data ? (
          <DashboardContent
            stats={dashboardQuery.data.stats}
            dueConcepts={dashboardQuery.data.dueConcepts}
            actionSummary={dashboardQuery.data.actionSummary}
            topicMap={dashboardQuery.data.topicMap}
          />
        ) : null}
      </section>
    </AppLayout>
  );
}

function DashboardContent({
  stats,
  dueConcepts,
  actionSummary,
  topicMap,
}: DashboardBundle) {
  const byId = new Map(topicMap.map((topic) => [topic.id, topic]));
  const roots = topicMap.filter((topic) => !topic.parent_ids.length).sort((left, right) => left.title.localeCompare(right.title));
  const seen = new Set<number>();
  const orphaned = topicMap
    .filter((topic) => !roots.some((root) => root.id === topic.id))
    .filter((topic) => !seen.has(topic.id))
    .sort((left, right) => left.title.localeCompare(right.title));

  return (
    <div className="grid min-h-0 gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,0.7fr)] xl:grid-rows-[auto_minmax(0,1fr)]">
      <div className="grid gap-3 sm:grid-cols-2 xl:col-span-2 xl:grid-cols-5">
        {[
          { label: 'Concepts', value: stats.total_concepts },
          { label: 'Topics', value: topicMap.length },
          { label: 'Due Now', value: stats.due_now },
          { label: 'Reviews (7d)', value: stats.reviews_last_7d },
          { label: 'Avg Score', value: `${stats.avg_mastery}/100` },
        ].map((item) => (
          <Card key={item.label} className="bg-panel-muted/70">
            <CardContent className="flex min-h-28 flex-col justify-between py-6">
              <div className="text-3xl font-semibold tracking-tight text-foreground">{item.value}</div>
              <div className="text-xs uppercase tracking-[0.24em] text-muted-foreground">{item.label}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="flex min-h-0 flex-col xl:row-span-1">
        <CardHeader>
          <CardTitle>Due for Review</CardTitle>
          <CardDescription>Concepts that should be revisited next.</CardDescription>
        </CardHeader>
        <CardContent className="min-h-0 flex-1">
        {dueConcepts.length ? (
          <div className="app-scrollbar h-full overflow-auto">
            <table className="w-full border-separate border-spacing-0 text-left text-sm text-slate-200">
              <thead>
                <tr className="text-xs uppercase tracking-[0.2em] text-muted-foreground">
                  <th className="border-b border-border/80 px-4 py-3">Concept</th><th className="border-b border-border/80 px-4 py-3">Score</th><th className="border-b border-border/80 px-4 py-3">Due</th>
                </tr>
              </thead>
              <tbody>
                {dueConcepts.map((concept) => (
                  <tr key={concept.id} className="transition-colors hover:bg-secondary/50">
                    <td className="border-b border-border/40 px-4 py-3"><Link className="font-medium text-primary transition-colors hover:text-primary/80" to={`/concept/${concept.id}`}>{concept.title}</Link></td>
                    <td className="border-b border-border/40 px-4 py-3 text-foreground">{concept.mastery_level}/100</td>
                    <td className="border-b border-border/40 px-4 py-3 text-muted-foreground">{concept.next_review_at || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <p className="text-sm text-muted-foreground">No concepts due for review right now.</p>}
        </CardContent>
      </Card>

      <div className="grid min-h-0 gap-4 xl:grid-rows-[auto_minmax(0,1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Recent Activity</CardTitle>
            <CardDescription>High-level operational summary from the last seven days.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <p className="text-foreground">Today: {summarizeActivity(actionSummary.today_by_action)} ({actionSummary.today_total} total)</p>
            <p className="text-muted-foreground">This week: {summarizeActivity(actionSummary.by_action)} ({actionSummary.total} total)</p>
            <p><Link className="font-medium text-primary transition-colors hover:text-primary/80" to="/actions">View full activity log →</Link></p>
          </CardContent>
        </Card>

        <Card className="flex min-h-0 flex-col">
          <CardHeader>
            <CardTitle>Topics</CardTitle>
            <CardDescription>Current topic structure with concept and due counts.</CardDescription>
          </CardHeader>
          <CardContent className="min-h-0 flex-1">
          {topicMap.length ? (
            <div className="app-scrollbar h-full overflow-auto rounded-2xl border border-border/60 bg-background/35 p-4">
              <div className="topic-tree">
                <ul className="space-y-3">
                  {roots.map((topic) => (
                    <TopicTree key={topic.id} node={topic} byId={byId} seen={seen} />
                  ))}
                  {orphaned.filter((topic) => !seen.has(topic.id)).map((topic) => (
                    <TopicTree key={topic.id} node={topic} byId={byId} seen={seen} />
                  ))}
                </ul>
              </div>
            </div>
          ) : <p className="text-sm text-muted-foreground">No topics yet.</p>}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}