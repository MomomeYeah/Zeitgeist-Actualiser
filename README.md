# Zeitgeist Actualiser

Scrapes social platforms, works out what is trending, and generates memes about it.

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

Fill in `.env`. The only value you must supply is `ANTHROPIC_API_KEY` (or
switch to Ollama, below). `SOURCES` picks the platforms to scrape.

### Sources

`SOURCES=lemmy` is the default and needs no credentials — Lemmy's API is
public and unauthenticated. `LEMMY_INSTANCE` chooses the instance to query;
because instances federate, one already returns posts from across the
network. `LEMMY_INCLUDE_NSFW` maps to the API's own `show_nsfw` flag and is
off by default.

Reddit is implemented and tested but ships disabled. Reddit's
[Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)
requires approved access before using the Data API, and the self-serve route
at `/prefs/apps` no longer issues credentials. If you are granted access, set
`REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` and add it to the list:

```
SOURCES=lemmy,reddit
```

Enabling `reddit` without both credentials fails at startup with a message
naming the missing variables.

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
