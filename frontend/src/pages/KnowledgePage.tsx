import { lazy, Suspense, useEffect, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { LoadingCard } from '@/components/LoadingCard';
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable-panels';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { PageIntro } from '@/components/PageIntro';
import { useLocation, useNavigate } from 'react-router-dom';
import { ConceptsCatalogView } from './ConceptsListPage';
import { ConceptDetailView } from './ConceptDetailPage';
import { TopicDetailView } from './TopicDetailPage';
import { TopicsExplorerView } from './TopicsListPage';

const GraphExplorerView = lazy(async () => {
  const module = await import('./GraphPage');
  return { default: module.GraphExplorerView };
});

type KnowledgeTab = 'topics' | 'concepts' | 'graph';

function resolveKnowledgeTab(pathname: string): KnowledgeTab {
  if (pathname === '/knowledge/concepts' || pathname === '/concepts') {
    return 'concepts';
  }
  if (pathname === '/knowledge/graph' || pathname === '/graph') {
    return 'graph';
  }
  return 'topics';
}

function routeForTab(tab: string) {
  if (tab === 'concepts') {
    return '/knowledge/concepts';
  }
  if (tab === 'graph') {
    return '/knowledge/graph';
  }
  return '/knowledge';
}

function GraphTabFallback() {
  return <LoadingCard label="Loading graph…" rows={3} />;
}

function useDesktopKnowledgePanels() {
  const [isDesktop, setIsDesktop] = useState(() => (typeof window === 'undefined' ? true : window.innerWidth >= 1280));

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }

    function updateViewportMode() {
      setIsDesktop(window.innerWidth >= 1280);
    }

    updateViewportMode();
    window.addEventListener('resize', updateViewportMode);
    return () => window.removeEventListener('resize', updateViewportMode);
  }, []);

  return isDesktop;
}

function KnowledgeDetailPlaceholder({ title, description, note }: { title: string; description: string; note: string }) {
  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">{note}</CardContent>
    </Card>
  );
}

function KnowledgeSplitLayout({
  storageId,
  isDesktop,
  primary,
  detail,
}: {
  storageId: string;
  isDesktop: boolean;
  primary: React.ReactNode;
  detail: React.ReactNode;
}) {
  return (
    <ResizablePanelGroup
      direction={isDesktop ? 'horizontal' : 'vertical'}
      autoSaveId={storageId}
      className="min-h-0"
    >
      <ResizablePanel defaultSize={58} minSize={isDesktop ? 36 : 42} className="min-h-0">
        <div className="h-full min-h-0">{primary}</div>
      </ResizablePanel>
      <ResizableHandle aria-label="Resize knowledge panels" />
      <ResizablePanel defaultSize={42} minSize={isDesktop ? 24 : 28} className="min-h-0">
        <div className="h-full min-h-0">{detail}</div>
      </ResizablePanel>
    </ResizablePanelGroup>
  );
}

export function KnowledgePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const currentTab = resolveKnowledgeTab(location.pathname);
  const [selectedTopicId, setSelectedTopicId] = useState<number | null>(null);
  const [selectedConceptId, setSelectedConceptId] = useState<number | null>(null);
  const isDesktop = useDesktopKnowledgePanels();

  return (
    <section className="grid h-full min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-5">
      <PageIntro
        eyebrow="Knowledge"
        title="Knowledge explorer"
        description="Topics, concepts, and graph exploration are now grouped into one surface so navigation stays inside the same operating context."
        aside={
          <>
            <Badge variant="outline">Topics + concepts + graph</Badge>
            <Badge variant="muted">Legacy routes still supported</Badge>
          </>
        }
      />

      <Tabs
        value={currentTab}
        onValueChange={(nextTab) => navigate(routeForTab(nextTab))}
        className="grid min-h-0 grid-rows-[auto_minmax(0,1fr)] gap-4"
      >
        <TabsList>
          <TabsTrigger value="topics">Topics</TabsTrigger>
          <TabsTrigger value="concepts">Concepts</TabsTrigger>
          <TabsTrigger value="graph">Graph</TabsTrigger>
        </TabsList>

        <TabsContent value="topics" className="min-h-0">
          <KnowledgeSplitLayout
            storageId="knowledge-topics-layout"
            isDesktop={isDesktop}
            primary={
              <TopicsExplorerView
                showHeader={false}
                selectedTopicId={selectedTopicId}
                onSelectTopic={setSelectedTopicId}
              />
            }
            detail={selectedTopicId ? (
              <TopicDetailView
                topicId={selectedTopicId}
                showHeader={false}
                embedded
                onSelectTopic={setSelectedTopicId}
              />
            ) : (
              <KnowledgeDetailPlaceholder
                title="Topic detail panel"
                description="Select a topic from the explorer to inspect linked concepts and nearby hierarchy without leaving Knowledge."
                note="The standalone topic route stays available while this inline workflow is being evaluated."
              />
            )}
          />
        </TabsContent>

        <TabsContent value="concepts" className="min-h-0">
          <KnowledgeSplitLayout
            storageId="knowledge-concepts-layout"
            isDesktop={isDesktop}
            primary={
              <ConceptsCatalogView
                showHeader={false}
                selectedConceptId={selectedConceptId}
                onSelectConcept={setSelectedConceptId}
              />
            }
            detail={selectedConceptId ? (
              <ConceptDetailView
                conceptId={selectedConceptId}
                showHeader={false}
                embedded
                onSelectConcept={setSelectedConceptId}
              />
            ) : (
              <KnowledgeDetailPlaceholder
                title="Concept detail panel"
                description="Select a concept from the catalog to inspect review state, relations, and remarks without leaving Knowledge."
                note="The standalone concept route stays available while this inline workflow is being evaluated."
              />
            )}
          />
        </TabsContent>

        <TabsContent value="graph" className="min-h-0">
          {currentTab === 'graph' ? (
            <Suspense fallback={<GraphTabFallback />}>
              <GraphExplorerView showHeader={false} />
            </Suspense>
          ) : null}
        </TabsContent>
      </Tabs>
    </section>
  );
}