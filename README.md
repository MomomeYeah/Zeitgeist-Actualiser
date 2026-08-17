# Zeitgeist Actualiser

Scrapes Reddit, works out what is trending, and generates memes about it.

## Setup

Install [uv](https://docs.astral.sh/uv/), then:

```bash
uv sync
```

That creates `.venv/`, installs the exact versions in `uv.lock`, and fetches
the Python version named in `.python-version` if you do not have it. Then copy
the config template:

```bash
copy .env.example .env
```

Fill in `.env`. Reddit credentials come from
https://www.reddit.com/prefs/apps — create a **script** app; the pipeline uses
read-only access, so no user login is needed.

## Running

```bash
uv run zeitgeist run
```

Output lands in `output/<run-id>/`: the four stage checkpoints as JSON, plus
one PNG per selected topic.

Re-run only the meme generation against an existing run, which is how you tune
caption prompts without re-scraping or paying for analysis again:

```bash
uv run zeitgeist run --run-id 20260816T120000Z --resume-from generate
```

Check the template library after editing a manifest:

```bash
uv run zeitgeist validate-templates
```

## Using a local model

Install Ollama, pull a model, then set in `.env`:

```
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:14b
```

Nothing else changes. Comparing the two backends on identical input is the
point of the provider abstraction.

## Tests

```bash
uv run pytest
```

No test touches the network. Every LLM call goes through `FakeLLMProvider`.
