import { Suspense } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppShell } from './components/AppShell';
import { ChatPage } from './pages/ChatPage';
import { ConceptDetailPage } from './pages/ConceptDetailPage';
import { DashboardPage } from './pages/DashboardPage';
import { ActivityPage } from './pages/ActivityPage';
import { KnowledgePage } from './pages/KnowledgePage';
import { ProgressPage } from './pages/ProgressPage';
import { TopicDetailPage } from './pages/TopicDetailPage';

const queryClient = new QueryClient();

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
            <Route element={<AppShell />}>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/actions" element={<ActivityPage />} />
              <Route path="/chat" element={<ChatPage />} />
              <Route path="/concept/:conceptId" element={<ConceptDetailPage />} />
              <Route path="/concepts" element={<Navigate to="/knowledge/concepts" replace />} />
              <Route path="/forecast" element={<Navigate to="/progress/forecast" replace />} />
              <Route path="/graph" element={<Navigate to="/knowledge/graph" replace />} />
              <Route path="/knowledge" element={<KnowledgePage />} />
              <Route path="/knowledge/concepts" element={<KnowledgePage />} />
              <Route path="/knowledge/graph" element={<KnowledgePage />} />
              <Route path="/progress" element={<ProgressPage />} />
              <Route path="/progress/forecast" element={<ProgressPage />} />
              <Route path="/topic/:topicId" element={<TopicDetailPage />} />
              <Route path="/topics" element={<Navigate to="/knowledge" replace />} />
              <Route path="/reviews" element={<Navigate to="/progress" replace />} />
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
  );
}