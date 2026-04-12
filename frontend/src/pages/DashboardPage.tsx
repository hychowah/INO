import { useQuery } from '@tanstack/react-query';
import { AppLayout } from '../components/AppLayout';
import { fetchActionSummary, fetchDueConcepts, fetchReviewStats, fetchTopicMap } from '../api';
import { resolveBackendHref } from '../lib/navigation';
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
    <li>
      <a href={resolveBackendHref(`/topic/${node.id}`)}>{node.title}</a>
      <span className="topic-meta"> {node.concept_count} concepts, {node.due_count} due</span>
      {children.length ? (
        <ul>
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
      <div className="chat-page">
        <div className="chat-shell">
          <div className="chat-header">
            <h2>Dashboard</h2>
            <p className="chat-subtitle">React dashboard shell backed by the FastAPI API.</p>
          </div>

          {dashboardQuery.isPending ? <div className="card">Loading dashboard…</div> : null}
          {dashboardQuery.isError ? <div className="card chat-bubble-error">{(dashboardQuery.error as Error).message}</div> : null}

          {dashboardQuery.data ? (
            <DashboardContent
              stats={dashboardQuery.data.stats}
              dueConcepts={dashboardQuery.data.dueConcepts}
              actionSummary={dashboardQuery.data.actionSummary}
              topicMap={dashboardQuery.data.topicMap}
            />
          ) : null}
        </div>
      </div>
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
    <>
      <div className="stats">
        <div className="stat"><div className="num">{stats.total_concepts}</div><div className="label">Concepts</div></div>
        <div className="stat"><div className="num">{topicMap.length}</div><div className="label">Topics</div></div>
        <div className="stat"><div className="num">{stats.due_now}</div><div className="label">Due Now</div></div>
        <div className="stat"><div className="num">{stats.reviews_last_7d}</div><div className="label">Reviews (7d)</div></div>
        <div className="stat"><div className="num">{stats.avg_mastery}/100</div><div className="label">Avg Score</div></div>
      </div>

      <div className="card">
        <h3>⏰ Due for Review</h3>
        {dueConcepts.length ? (
          <table>
            <thead>
              <tr><th>Concept</th><th>Score</th><th>Due</th></tr>
            </thead>
            <tbody>
              {dueConcepts.map((concept) => (
                <tr key={concept.id}>
                  <td><a href={resolveBackendHref(`/concept/${concept.id}`)}>{concept.title}</a></td>
                  <td>{concept.mastery_level}/100</td>
                  <td>{concept.next_review_at || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p>No concepts due for review right now.</p>}
      </div>

      <div className="card">
        <h3>📋 Recent Activity</h3>
        <p style={{ fontSize: '14px', margin: '6px 0' }}>Today: {summarizeActivity(actionSummary.today_by_action)} ({actionSummary.today_total} total)</p>
        <p style={{ fontSize: '14px', margin: '6px 0', color: 'var(--text2)' }}>This week: {summarizeActivity(actionSummary.by_action)} ({actionSummary.total} total)</p>
        <p style={{ marginTop: '10px' }}><a href={resolveBackendHref('/actions')}>View full activity log →</a></p>
      </div>

      <div className="card">
        <h3>🗂 Topics</h3>
        {topicMap.length ? (
          <div className="topic-tree">
            <ul>
              {roots.map((topic) => (
                <TopicTree key={topic.id} node={topic} byId={byId} seen={seen} />
              ))}
              {orphaned.filter((topic) => !seen.has(topic.id)).map((topic) => (
                <TopicTree key={topic.id} node={topic} byId={byId} seen={seen} />
              ))}
            </ul>
          </div>
        ) : <p>No topics yet.</p>}
      </div>
    </>
  );
}