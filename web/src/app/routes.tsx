import { Route, Routes } from "react-router-dom";

import { AppLayout } from "@/app/AppLayout";
import { EmptyState } from "@/components/EmptyState";
import { NewRunPage } from "@/features/newrun/NewRunPage";
import { RenderDetailPage } from "@/features/renders/RenderDetailPage";
import { RunDetailPage } from "@/features/runs/RunDetailPage";
import { RunsPage } from "@/features/runs/RunsPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { TopicDetailPage } from "@/features/topics/TopicDetailPage";
import { TopicsPage } from "@/features/topics/TopicsPage";

/**
 * Seven routes. Topic detail is run-scoped because the dossier, the
 * replies and the renders all belong to one run, and because generating a
 * meme needs an unambiguous run to attach to.
 *
 * `/runs/new` sits before `/runs/:runId` so the literal wins; React Router
 * ranks static segments above dynamic ones regardless, and the order here
 * says so to a reader.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route path="/" element={<TopicsPage />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/runs/new" element={<NewRunPage />} />
        <Route path="/runs/:runId" element={<RunDetailPage />} />
        <Route
          path="/runs/:runId/renders/:renderId"
          element={<RenderDetailPage />}
        />
        <Route path="/topics/:runId/:topicId" element={<TopicDetailPage />} />
        <Route path="/settings" element={<SettingsPage />} />
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
