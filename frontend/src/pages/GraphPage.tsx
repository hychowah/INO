import { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import ForceGraph2D from 'react-force-graph-2d';
import { forceCenter, forceX, forceY } from 'd3-force';
import { Link, useNavigate } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LoadingCard } from '@/components/LoadingCard';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { fetchGraph } from '../api';
import type { GraphResponse } from '../types';

const DEFAULT_MAX_NODES = 500;
const TOPIC_COLOR = '#58a6ff';
const RELATION_COLORS: Record<string, string> = {
  builds_on: '#4CAF50',
  contrasts_with: '#FF9800',
  commonly_confused: '#F44336',
  applied_together: '#2196F3',
  same_phenomenon: '#9C27B0',
};

const MASTERY_FILTERS = {
  all: { label: 'All' },
  struggling: { label: 'Struggling', min: 0, max: 24 },
  building: { label: 'Building', min: 25, max: 49 },
  solid: { label: 'Solid', min: 50, max: 74 },
  mastered: { label: 'Mastered', min: 75, max: 100 },
} as const;

type MasteryFilter = keyof typeof MASTERY_FILTERS;
type LayoutMode = 'force' | 'cluster';

type GraphViewNode = {
  id: string;
  rawId: number;
  kind: 'concept' | 'topic';
  label: string;
  description?: string | null;
  mastery: number;
  reviewCount: number;
  nextReviewAt?: string | null;
  intervalDays?: number | null;
  topicIds: number[];
  topicNames?: string | null;
  x?: number;
  y?: number;
};

type GraphViewLink = {
  source: string | GraphViewNode;
  target: string | GraphViewNode;
  edgeType: 'relation' | 'membership' | 'hierarchy';
  relationType?: string;
  note?: string | null;
};

type GraphExplorerViewProps = {
  showHeader?: boolean;
};

function formatDue(dateStr?: string | null) {
  if (!dateStr) {
    return 'No review scheduled';
  }

  const parsed = new Date(dateStr.replace(' ', 'T'));
  if (Number.isNaN(parsed.getTime())) {
    return dateStr;
  }

  const diffHours = (parsed.getTime() - Date.now()) / 3600000;
  if (diffHours <= 0) {
    return 'Due now';
  }
  if (diffHours < 24) {
    return `Due in ${Math.round(diffHours)}h`;
  }
  return `Due in ${Math.round(diffHours / 24)}d`;
}

function useElementSize() {
  const ref = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!ref.current) {
      return undefined;
    }

    const element = ref.current;
    const updateSize = () => {
      setSize({
        width: element.clientWidth,
        height: element.clientHeight,
      });
    };

    updateSize();

    const observer = new ResizeObserver(updateSize);
    observer.observe(element);

    return () => observer.disconnect();
  }, []);

  return { ref, size };
}

function buildGraphView(data: GraphResponse) {
  const visibleConceptIds = new Set(data.concept_nodes.map((concept) => concept.id));
  const membershipEdges = data.concept_topic_edges.filter((edge) => visibleConceptIds.has(edge.concept_id));
  const visibleTopicIds = new Set(membershipEdges.map((edge) => edge.topic_id));
  const topicNodes = data.topic_nodes.filter((topic) => visibleTopicIds.has(topic.id));

  const nodes: GraphViewNode[] = [
    ...topicNodes.map((topic) => ({
      id: `topic_${topic.id}`,
      rawId: topic.id,
      kind: 'topic' as const,
      label: topic.title,
      description: topic.description,
      mastery: 0,
      reviewCount: 0,
      topicIds: [],
    })),
    ...data.concept_nodes.map((concept) => ({
      id: `concept_${concept.id}`,
      rawId: concept.id,
      kind: 'concept' as const,
      label: concept.title,
      description: concept.description,
      mastery: concept.mastery_level || 0,
      reviewCount: concept.review_count || 0,
      nextReviewAt: concept.next_review_at,
      intervalDays: concept.interval_days,
      topicIds: concept.topic_ids || [],
      topicNames: concept.topic_names,
    })),
  ];

  const topicIdSet = new Set(topicNodes.map((topic) => topic.id));
  const links: GraphViewLink[] = [
    ...data.concept_edges
      .filter((edge) => visibleConceptIds.has(edge.concept_id_low) && visibleConceptIds.has(edge.concept_id_high))
      .map((edge) => ({
        source: `concept_${edge.concept_id_low}`,
        target: `concept_${edge.concept_id_high}`,
        edgeType: 'relation' as const,
        relationType: edge.relation_type,
        note: edge.note,
      })),
    ...membershipEdges.map((edge) => ({
      source: `concept_${edge.concept_id}`,
      target: `topic_${edge.topic_id}`,
      edgeType: 'membership' as const,
    })),
    ...data.topic_edges
      .filter((edge) => topicIdSet.has(edge.parent_id) && topicIdSet.has(edge.child_id))
      .map((edge) => ({
        source: `topic_${edge.parent_id}`,
        target: `topic_${edge.child_id}`,
        edgeType: 'hierarchy' as const,
      })),
  ];

  return { nodes, links };
}

export function GraphExplorerView({ showHeader = true }: GraphExplorerViewProps) {
  const navigate = useNavigate();
  const graphRef = useRef<any>(null);
  const { ref: containerRef, size } = useElementSize();
  const [topicId, setTopicId] = useState('');
  const [masteryFilter, setMasteryFilter] = useState<MasteryFilter>('all');
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('force');
  const [search, setSearch] = useState('');
  const [hoveredNode, setHoveredNode] = useState<GraphViewNode | null>(null);
  const [hoveredLink, setHoveredLink] = useState<GraphViewLink | null>(null);
  const deferredSearch = useDeferredValue(search.trim().toLowerCase());
  const fitPendingRef = useRef(true);
  const graphWidth = size.width || 960;
  const graphHeight = size.height || 620;

  const masteryRange = MASTERY_FILTERS[masteryFilter];
  const graphQuery = useQuery<GraphResponse>({
    queryKey: ['graph', topicId, masteryFilter],
    queryFn: () => fetchGraph({
      topicId: topicId ? Number(topicId) : undefined,
      minMastery: 'min' in masteryRange ? masteryRange.min : undefined,
      maxMastery: 'max' in masteryRange ? masteryRange.max : undefined,
      maxNodes: DEFAULT_MAX_NODES,
    }),
  });

  const graphData = useMemo(() => (graphQuery.data ? buildGraphView(graphQuery.data) : { nodes: [], links: [] }), [graphQuery.data]);
  const topicOptions = useMemo(
    () => (graphQuery.data?.topic_nodes || []).slice().sort((left, right) => left.title.localeCompare(right.title)),
    [graphQuery.data]
  );
  const matchedNodeIds = useMemo(() => {
    if (!deferredSearch) {
      return null;
    }

    return new Set(
      graphData.nodes
        .filter((node) => node.label.toLowerCase().includes(deferredSearch))
        .map((node) => node.id)
    );
  }, [deferredSearch, graphData.nodes]);

  useEffect(() => {
    fitPendingRef.current = true;
  }, [graphData.nodes.length, graphData.links.length, layoutMode]);

  useEffect(() => {
    const instance = graphRef.current;
    if (!instance || !graphData.nodes.length) {
      return;
    }

    if (layoutMode === 'cluster') {
      const topicNodes = graphData.nodes.filter((node) => node.kind === 'topic');
      const positions = new Map<string, { x: number; y: number }>();
      const angleStep = (2 * Math.PI) / Math.max(topicNodes.length, 1);
      const radius = Math.min(graphWidth, graphHeight) * 0.32;

      topicNodes.forEach((node, index) => {
        const angle = index * angleStep - Math.PI / 2;
        positions.set(node.id, {
          x: graphWidth / 2 + radius * Math.cos(angle),
          y: graphHeight / 2 + radius * Math.sin(angle),
        });
      });

      instance.d3Force('center', null);
      instance.d3Force('x', forceX((node: GraphViewNode) => {
        if (node.kind === 'topic') {
          return positions.get(node.id)?.x ?? graphWidth / 2;
        }
        const topicTarget = node.topicIds[0] ? positions.get(`topic_${node.topicIds[0]}`) : null;
        return topicTarget?.x ?? graphWidth / 2;
      }).strength(0.25));
      instance.d3Force('y', forceY((node: GraphViewNode) => {
        if (node.kind === 'topic') {
          return positions.get(node.id)?.y ?? graphHeight / 2;
        }
        const topicTarget = node.topicIds[0] ? positions.get(`topic_${node.topicIds[0]}`) : null;
        return topicTarget?.y ?? graphHeight / 2;
      }).strength(0.25));
    } else {
      instance.d3Force('x', null);
      instance.d3Force('y', null);
      instance.d3Force('center', forceCenter(graphWidth / 2, graphHeight / 2));
    }

    instance.d3ReheatSimulation();
  }, [graphData.nodes, graphHeight, graphWidth, layoutMode]);

  useEffect(() => {
    if (!deferredSearch || !matchedNodeIds?.size) {
      return;
    }

    const instance = graphRef.current;
    const target = graphData.nodes.find((node) => matchedNodeIds.has(node.id) && typeof node.x === 'number' && typeof node.y === 'number');
    if (!instance || !target || typeof target.x !== 'number' || typeof target.y !== 'number') {
      return;
    }

    instance.centerAt(target.x, target.y, 500);
    instance.zoom(2, 500);
  }, [deferredSearch, matchedNodeIds, graphData.nodes]);

  function nodeAlpha(node: GraphViewNode) {
    if (!matchedNodeIds) {
      return 1;
    }
    return matchedNodeIds.has(node.id) ? 1 : 0.18;
  }

  function linkColor(link: GraphViewLink) {
    const sourceId = typeof link.source === 'string' ? link.source : link.source.id;
    const targetId = typeof link.target === 'string' ? link.target : link.target.id;
    const highlighted = matchedNodeIds ? matchedNodeIds.has(sourceId) || matchedNodeIds.has(targetId) : true;

    if (link.edgeType === 'relation') {
      const base = RELATION_COLORS[link.relationType || ''] || '#c9d1d9';
      return highlighted ? base : 'rgba(201,209,217,0.12)';
    }
    if (link.edgeType === 'hierarchy') {
      return highlighted ? 'rgba(88,166,255,0.5)' : 'rgba(88,166,255,0.12)';
    }
    return highlighted ? 'rgba(88,166,255,0.35)' : 'rgba(88,166,255,0.08)';
  }

  function nodeCanvasObject(nodeObject: object, context: CanvasRenderingContext2D, globalScale: number) {
    const node = nodeObject as GraphViewNode;
    const alpha = nodeAlpha(node);
    const fontSize = Math.max(10, 13 / globalScale);

    context.save();
    context.globalAlpha = alpha;

    if (node.kind === 'topic') {
      context.beginPath();
      context.fillStyle = TOPIC_COLOR;
      context.arc(node.x || 0, node.y || 0, 14, 0, 2 * Math.PI, false);
      context.fill();
      context.strokeStyle = 'rgba(255,255,255,0.45)';
      context.lineWidth = 1;
      context.stroke();
    } else {
      let fill = '#ef4444';
      if (node.mastery >= 75) fill = '#22c55e';
      else if (node.mastery >= 50) fill = '#84cc16';
      else if (node.mastery >= 25) fill = '#f59e0b';

      context.beginPath();
      context.fillStyle = fill;
      context.arc(node.x || 0, node.y || 0, 8, 0, 2 * Math.PI, false);
      context.fill();
      context.strokeStyle = 'rgba(255,255,255,0.25)';
      context.lineWidth = 1;
      context.stroke();

      if (matchedNodeIds?.has(node.id)) {
        context.beginPath();
        context.strokeStyle = 'rgba(255,255,255,0.75)';
        context.lineWidth = 2;
        context.arc(node.x || 0, node.y || 0, 12, 0, 2 * Math.PI, false);
        context.stroke();
      }
    }

    if (node.kind === 'topic' || graphData.nodes.length <= 30) {
      context.font = `${fontSize}px sans-serif`;
      context.textAlign = 'center';
      context.textBaseline = 'top';
      context.fillStyle = node.kind === 'topic' ? '#e6edf3' : '#8b949e';
      context.fillText(node.label.length > 22 ? `${node.label.slice(0, 20)}…` : node.label, node.x || 0, (node.y || 0) + (node.kind === 'topic' ? 18 : 12));
    }

    context.restore();
  }

  return (
    <section className="space-y-6">
      {showHeader ? (
        <div className="flex flex-col gap-3">
          <Badge className="w-fit">Knowledge Graph</Badge>
          <div>
            <h2 className="text-3xl font-semibold tracking-tight text-white">Graph</h2>
            <p className="mt-2 max-w-3xl text-sm text-slate-400">Explore concept relations, topic membership, and hierarchy inside the migrated React graph surface.</p>
          </div>
        </div>
      ) : null}

        {graphQuery.data && graphQuery.data.total_concepts > graphQuery.data.concept_nodes.length ? (
          <Card className="border-amber-400/20 bg-amber-400/10">
            <CardContent className="py-4 text-sm text-amber-50">Showing top {graphQuery.data.concept_nodes.length} of {graphQuery.data.total_concepts} concepts after filters. Narrow the graph to inspect a smaller slice.</CardContent>
          </Card>
        ) : null}

        <Card>
          <CardHeader>
            <CardTitle>Filters</CardTitle>
            <CardDescription>Topic and mastery filters are applied server-side. Search highlights nodes client-side.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)_minmax(0,0.8fr)]">
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search graph nodes..."
              />
              <Select
                value={topicId}
                onChange={(event) => setTopicId(event.target.value)}
              >
                <option value="">All Topics</option>
                {topicOptions.map((topic) => (
                  <option key={topic.id} value={topic.id}>{topic.title}</option>
                ))}
              </Select>
              <div className="flex flex-wrap gap-2">
                <Button type="button" size="sm" variant={layoutMode === 'force' ? 'default' : 'secondary'} onClick={() => setLayoutMode('force')}>Free Layout</Button>
                <Button type="button" size="sm" variant={layoutMode === 'cluster' ? 'default' : 'secondary'} onClick={() => setLayoutMode('cluster')}>Group by Topic</Button>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              {(Object.entries(MASTERY_FILTERS) as Array<[MasteryFilter, (typeof MASTERY_FILTERS)[MasteryFilter]]>).map(([value, filter]) => (
                <Button
                  key={value}
                  type="button"
                  size="sm"
                  variant={masteryFilter === value ? 'default' : 'secondary'}
                  onClick={() => setMasteryFilter(value)}
                >
                  {filter.label}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>

        {graphQuery.isPending ? <LoadingCard label="Loading graph…" rows={3} /> : null}

        {graphQuery.isError ? (
          <Card className="border-red-500/30 bg-red-500/10">
            <CardContent className="py-6 text-sm text-red-100">{(graphQuery.error as Error).message}</CardContent>
          </Card>
        ) : null}

        {graphQuery.data && !graphData.nodes.some((node) => node.kind === 'concept') ? (
          <Card>
            <CardContent className="py-6 text-sm text-slate-300">No concepts match the current graph filters.</CardContent>
          </Card>
        ) : null}

        {graphQuery.data && graphData.nodes.some((node) => node.kind === 'concept') ? (
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(320px,0.75fr)]">
            <Card>
              <CardHeader>
                <CardTitle>Map</CardTitle>
                <CardDescription>{graphData.nodes.filter((node) => node.kind === 'concept').length} concepts, {graphData.nodes.filter((node) => node.kind === 'topic').length} topics, {graphData.links.length} edges.</CardDescription>
              </CardHeader>
              <CardContent>
                <div ref={containerRef} className="h-[620px] overflow-hidden rounded-3xl border border-white/10 bg-slate-950/80">
                  <ForceGraph2D
                    ref={graphRef}
                    width={graphWidth}
                    height={graphHeight}
                    graphData={graphData}
                    nodeCanvasObject={nodeCanvasObject}
                    linkColor={(link) => linkColor(link as GraphViewLink)}
                    linkWidth={(link) => ((link as GraphViewLink).edgeType === 'relation' ? 2 : 1.2)}
                    linkLineDash={(link) => ((link as GraphViewLink).edgeType === 'relation' ? null : [6, 3])}
                    onNodeClick={(node) => {
                      const target = node as GraphViewNode;
                      navigate(target.kind === 'concept' ? `/concept/${target.rawId}` : `/topic/${target.rawId}`);
                    }}
                    onNodeHover={(node) => setHoveredNode((node as GraphViewNode | null) ?? null)}
                    onLinkHover={(link) => setHoveredLink((link as GraphViewLink | null) ?? null)}
                    cooldownTicks={120}
                    onEngineStop={() => {
                      if (!fitPendingRef.current || !graphRef.current) {
                        return;
                      }
                      graphRef.current.zoomToFit(400, 60);
                      fitPendingRef.current = false;
                    }}
                  />
                </div>
              </CardContent>
            </Card>

            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle>Legend</CardTitle>
                  <CardDescription>Concept color reflects mastery. Blue nodes are topics.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3 text-sm text-slate-300">
                  <LegendRow color="#ef4444" label="Struggling" />
                  <LegendRow color="#f59e0b" label="Building" />
                  <LegendRow color="#84cc16" label="Solid" />
                  <LegendRow color="#22c55e" label="Mastered" />
                  <LegendRow color={TOPIC_COLOR} label="Topic" />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Inspector</CardTitle>
                  <CardDescription>Hover a node or relation to inspect it without leaving the graph.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3 text-sm text-slate-300">
                  {hoveredNode ? (
                    <>
                      <div className="text-base font-medium text-white">{hoveredNode.label}</div>
                      <div className="flex flex-wrap gap-2">
                        <Badge variant="outline">{hoveredNode.kind === 'topic' ? 'Topic' : `Score ${hoveredNode.mastery}`}</Badge>
                        {hoveredNode.kind === 'concept' ? <Badge variant="outline">{hoveredNode.reviewCount} reviews</Badge> : null}
                      </div>
                      {hoveredNode.kind === 'concept' ? <div>{formatDue(hoveredNode.nextReviewAt)}{hoveredNode.intervalDays ? ` · ${hoveredNode.intervalDays}d interval` : ''}</div> : null}
                      {hoveredNode.topicNames ? <div className="text-slate-400">Topics: {hoveredNode.topicNames}</div> : null}
                      {hoveredNode.description ? <p className="text-slate-400">{hoveredNode.description}</p> : null}
                    </>
                  ) : hoveredLink ? (
                    <>
                      <div className="text-base font-medium text-white">{hoveredLink.edgeType === 'relation' ? hoveredLink.relationType?.split('_').join(' ') : hoveredLink.edgeType}</div>
                      {hoveredLink.note ? <p className="text-slate-400">{hoveredLink.note}</p> : null}
                    </>
                  ) : (
                    <p className="text-slate-400">Nothing selected yet. Hover a node or edge.</p>
                  )}
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>Fallback</CardTitle>
                  <CardDescription>On smaller screens, list views are often easier to scan.</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3 text-sm text-slate-300">
                  <p>If you need a denser view, jump back to the migrated lists instead of fighting the canvas.</p>
                  <div className="flex flex-wrap gap-2">
                    <Link className="inline-flex rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 transition-colors hover:border-white/20 hover:bg-white/10" to="/topics">Topics</Link>
                    <Link className="inline-flex rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 transition-colors hover:border-white/20 hover:bg-white/10" to="/concepts">Concepts</Link>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        ) : null}
    </section>
  );
}

export function GraphPage() {
  return <GraphExplorerView />;
}

function LegendRow({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="h-3 w-3 rounded-full" style={{ backgroundColor: color }} />
      <span>{label}</span>
    </div>
  );
}