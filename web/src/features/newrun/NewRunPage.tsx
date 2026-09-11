import type { FormEvent } from "react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import type { ConfigOptions, RunConfig } from "@/api/types";
import { useActiveRun, useConfigOptions, useRun, useStartRun } from "@/api/queries";
import { Breadcrumb } from "@/components/Breadcrumb";
import { MetaLine } from "@/components/MetaLine";
import { QueryBoundary } from "@/components/QueryBoundary";
import { CountCard } from "@/features/newrun/CountCard";
import { frozenTunables } from "@/features/newrun/frozen";
import { ModelCard } from "@/features/newrun/ModelCard";
import { PlatformCard } from "@/features/newrun/PlatformCard";
import { TemplateCard } from "@/features/newrun/TemplateCard";
import { shortRunId } from "@/format";

import styles from "./NewRunPage.module.css";

export function NewRunPage() {
  const [params] = useSearchParams();
  const from = params.get("from") ?? undefined;
  const options = useConfigOptions();
  const source = useRun(from);

  return (
    <QueryBoundary query={options} missing="No configuration.">
      {(config) => (
        <div className={styles.page}>
          <Breadcrumb trail={[{ label: "Runs", to: "/runs" }, { label: "new" }]} />
          <header className={styles.header}>
            <h1 className={styles.title}>New run</h1>
            <MetaLine>
              {from !== undefined ? (
                // Re-running: every frozen field, not just the four cards
                // someone can see and edit, is about to be replayed — the
                // settings link is dropped because nothing here comes from
                // settings while a preset fills the form.
                <>
                  re-running {shortRunId(from)} · its frozen config fills every
                  field · changes apply to this run only
                </>
              ) : (
                <>
                  defaults come from <Link to="/settings">settings</Link> · changes
                  apply to this run only
                </>
              )}
            </MetaLine>
          </header>

          {/* The form owns its state and seeds it from props, so the
              seeding happens once, at mount, rather than in an effect that
              has to decide whether the user has since edited a field. That
              means waiting for the source run before mounting it. */}
          {from !== undefined && source.data === undefined ? (
            <p className={styles.loading}>Loading that run's config…</p>
          ) : (
            <NewRunForm config={config} preset={source.data?.run.config} />
          )}
        </div>
      )}
    </QueryBoundary>
  );
}

function NewRunForm({
  config,
  preset,
}: {
  config: ConfigOptions;
  preset?: RunConfig;
}) {
  const navigate = useNavigate();
  const active = useActiveRun();
  const start = useStartRun();

  const [provider, setProvider] = useState(
    preset?.llm_provider ?? config.defaults.llm_provider ?? "anthropic",
  );
  const [model, setModel] = useState(
    preset?.llm_model ?? config.defaults.llm_model ?? "",
  );
  const [platform, setPlatform] = useState(
    // Not `config.defaults.sources`: `options.py` stringifies every default
    // and `Settings.sources` is a list, so that key arrives as the Python
    // repr `"['bluesky']"` rather than a platform name. The enabled
    // platform is the honest default and there is exactly one.
    preset?.sources[0] ?? config.platforms.find((one) => one.enabled)?.name ?? "",
  );
  const [count, setCount] = useState(
    preset?.top_count ?? Number(config.defaults.topic_count ?? "5"),
  );
  const [templateIds, setTemplateIds] = useState<string[] | null>(
    preset?.template_ids ?? null,
  );

  function chooseProvider(next: string) {
    setProvider(next);
    // The model list is per-provider, so a model carried over from the old
    // one would post `claude-sonnet-5` to ollama and fail on the worker
    // thread with a model nobody chose.
    const available = config.models[next] ?? [];
    if (!available.includes(model)) setModel(available[0] ?? "");
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    start.mutate(
      {
        template_ids: templateIds,
        overrides: {
          // The six tunables the four cards don't cover, replayed exactly
          // as the source run froze them — spread first so the explicit
          // fields below (form state, not the preset) always win on any
          // overlap, though today there is none: the two key sets are
          // disjoint by construction.
          ...(preset !== undefined ? frozenTunables(preset) : {}),
          llm_provider: provider,
          llm_model: model,
          // A bare name: `Settings._split_csv` accepts a CSV string, and
          // the config's own validator enforces exactly one.
          sources: platform,
          topic_count: String(count),
        },
      },
      {
        onSuccess: (queued) => {
          void navigate(`/runs/${encodeURIComponent(queued.run_id)}`);
        },
      },
    );
  }

  const queuedBehind = active.data?.current ?? null;

  return (
    <form className={styles.layout} onSubmit={submit}>
      <div className={styles.cards}>
        <ModelCard
          models={config.models}
          provider={provider}
          model={model}
          keyPresent={config.anthropic_key_present}
          onProvider={chooseProvider}
          onModel={setModel}
        />
        <PlatformCard
          platforms={config.platforms}
          selected={platform}
          onSelect={setPlatform}
        />
        <CountCard
          count={count}
          // The frozen `trend_limit` while re-running, not the settings
          // default: this run already fixed how many trends it analysed,
          // and the note has to say what actually happened, not what a
          // fresh run would do today.
          trendLimit={
            preset !== undefined
              ? String(preset.trend_limit)
              : (config.defaults.bluesky_trend_limit ?? "25")
          }
          onCount={setCount}
        />
        <TemplateCard
          templates={config.templates}
          selected={templateIds}
          onSelect={setTemplateIds}
        />
      </div>

      <aside className={styles.side}>
        {queuedBehind !== null && (
          <p className={styles.notice}>
            A run is already in flight. Starting this one queues it behind{" "}
            {shortRunId(queuedBehind)}.
          </p>
        )}
        <button type="submit" className={styles.start} disabled={start.isPending}>
          Start run
        </button>
        {start.error !== null && <p className={styles.failure}>{start.error.detail}</p>}
      </aside>
    </form>
  );
}
