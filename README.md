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

`wikipedia` adds Wikimedia pageviews — the top 1000 most-viewed articles for
the most recent day with data. It needs no credentials. Unlike Lemmy it
measures *attention* rather than conversation: articles carry no comments and
no body text, so a topic Wikipedia alone found is dropped rather than
ranked. Its role is corroboration — a topic trending on Lemmy *and*
spiking on Wikipedia outranks one trending on Lemmy alone.

`WIKIPEDIA_CONTACT` is interpolated into the User-Agent. Wikimedia's API
policy asks for contact information and may rate-limit or block generic
agents, so set it to your own repository or contact URL if you fork this.

`bluesky` adds Bluesky posts and needs no credentials — the AT Protocol
AppView answers these endpoints unauthenticated. It fetches in two steps: the
25 current trends, then the posts behind each one. Bluesky maintains a live
feed for every trend, so the ranking within a topic is the platform's own
rather than ours.

Like Lemmy it is content-bearing, so it can originate topics rather than only
corroborate them. Unlike Lemmy its audience is general rather than technical,
which is the reason it is here. Two caveats worth knowing: trending skews
heavily toward US politics, which the sentiment weights push back against
rather than the source filtering out; and trend discovery uses an endpoint in
Bluesky's `unspecced` namespace, which is explicitly not a stable API. Reading
the posts themselves uses stable endpoints.

`BLUESKY_API_BASE` exists to point at a mirror and should not normally be
changed. Note that `public.api.bsky.app` is not a valid substitute — it
returns 403 on parts of the API.

Each platform scores its own contribution to a topic, normalised within that
platform, before the results are combined. So a busy platform no longer
swamps a quiet one, and mixing sources is expected rather than experimental.

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

## Running a local model

Install Ollama, and run a model locally:

```
ollama run qwen3.5
```

To view model details, run:

```
$ ollama show qwen3.5
  Model
    architecture        qwen35    
    parameters          9.7B      
    context length      262144    
    embedding length    4096      
    quantization        Q4_K_M    
    requires            0.17.1    

  Capabilities
    completion    
    vision        
    tools         
    thinking      

  Parameters
    presence_penalty    1.5     
    temperature         1       
    top_k               20      
    top_p               0.95    

  License
    Apache License               
    Version 2.0, January 2004    
    ...
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
