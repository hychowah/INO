import { lazy, Suspense } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { ChatPage } from './pages/ChatPage';
import { ConceptDetailPage } from './pages/ConceptDetailPage';
import { ConceptsListPage } from './pages/ConceptsListPage';
import { DashboardPage } from './pages/DashboardPage';
import { ActivityPage } from './pages/ActivityPage';
import { ProgressPage } from './pages/ProgressPage';
import { TopicDetailPage } from './pages/TopicDetailPage';
import { TopicsListPage } from './pages/TopicsListPage';

const queryClient = new QueryClient();
const GraphPage = lazy(async () => {
  const module = await import('./pages/GraphPage');
  return { default: module.GraphPage };
});

function RouteFallback() {
  return (
    <div className="mx-auto max-w-7xl px-4 pb-8 pt-6 text-sm text-slate-300 sm:px-6 lg:px-8">
      Loading page…
    </div>
  );
}

export function AppRouter() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Suspense fallback={<RouteFallback />}>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/actions" element={<ActivityPage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/concept/:conceptId" element={<ConceptDetailPage />} />
            <Route path="/concepts" element={<ConceptsListPage />} />
            <Route path="/forecast" element={<ProgressPage />} />
            <Route path="/graph" element={<GraphPage />} />
            <Route path="/progress" element={<ProgressPage />} />
            <Route path="/progress/forecast" element={<ProgressPage />} />
            <Route path="/topic/:topicId" element={<TopicDetailPage />} />
            <Route path="/topics" element={<TopicsListPage />} />
            <Route path="/reviews" element={<ProgressPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  );
}