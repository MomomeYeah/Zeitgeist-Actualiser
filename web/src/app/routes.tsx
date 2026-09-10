import { Route, Routes } from "react-router-dom";

import { AppLayout } from "@/app/AppLayout";
import { EmptyState } from "@/components/EmptyState";
import { RenderDetailPage } from "@/features/renders/RenderDetailPage";
import { RunDetailPage } from "@/features/runs/RunDetailPage";
import { RunsPage } from "@/features/runs/RunsPage";
import { TopicDetailPage } from "@/features/topics/TopicDetailPage";
import { TopicsPage } from "@/features/topics/TopicsPage";

/**
 * Five routes in this phase. Phase 6 adds `/runs/new` and `/settings`.
 *
 * Topic detail is run-scoped because the dossier, the replies and the
 * renders all belong to one run, and because generating a meme needs an
 * unambiguous run to attach to.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<TopicsPage />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route
          path="/runs/:runId/renders/:renderId"
          element={<RenderDetailPage />}
        />
        <Route path="/topics/:runId/:topicId" element={<TopicDetailPage />} />
        <Route
          path="*"
          element={
            <EmptyState
              headline="Nothing here"
              body="That address does not match any screen in this app."
            />
          }
        />
      </Route>
    </Routes>
  );
}
