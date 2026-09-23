---
title: Sfumato Idea Engine
emoji: 🌫️
colorFrom: purple
colorTo: blue
sdk: gradio
sdk_version: 6.28.0
app_file: app.py
pinned: false
---

# Sfumato Idea Engine

Sfumato generates independent idea seeds for a problem, then uses Jev
comparisons to select distinct directions and record their support. The
included skill guides the reasoning model you choose to examine each seed,
preserve its distinctive contribution, credit and rank it, and combine ideas
only when their mechanisms reinforce one another. Ideas that do not fit remain
standalone. Sfumato supplies directions to reason about; it does not choose a
final answer.

This repository contains the Gradio API and the `sfumato` agent skill.
The software is released under the MIT License; keep the copyright and license
notices with redistributed copies.

This Space turns a caller-written problem brief into a packet of ranked,
independent inspiration seeds. It does not compose the brief from a chat
transcript and does not run the final reasoning model. The caller chooses that
model.

## Configure provider keys

Add these as Space **Secrets** in the Space settings:

- `MERCURY_API_KEY`
- `TYPESAFE_API_KEY`

Do not add provider keys to files, normal Space variables, request fields, or
the Space card. The owner pays Mercury and Jev usage for every request. Keep the
funded prototype private. A later public template should be duplicated by each
user with their own provider keys.

Optional pricing overrides are ordinary environment variables:

- `SFUMATO_MERCURY_INPUT_USD_PER_M` (default `0.25`)
- `SFUMATO_MERCURY_OUTPUT_USD_PER_M` (default `0.75`)
- `SFUMATO_JEV_INPUT_USD_PER_M` (default `0.042`)

Costs in the packet are estimates from provider token counts and these configured
rates. Confirm provider pricing before relying on them.

## API

The named Gradio endpoint is `/generate_seed_packet`. Its fields are:

- `problem_brief`: concrete situation, objective, constraints, success condition,
  and exclusions; leave the mechanism open;
- `candidate_count`: `33` or `100`;
- `max_selected_seeds`: requested cap from `1` to `5` (the pipeline may return
  fewer when an unstable candidate is skipped near the pass limit);
- `trials_per_pass`: fixed at `8` for this release;
- `word_range`: `[minimum, maximum]`, default `[100, 180]`;
- `client_run_id`: optional caller label.

The endpoint returns the exact brief, selected seeds, support counts and option
mass, stopping/skip decisions, candidate hashes, token usage, and estimated API
cost. Jev values are attention-ranking scores, not calibrated probabilities.

With eight trials, a seed is marked `core` at six or more wins and `optional`
at four or five. Less stable selections are recorded as skipped and the next
pass continues. Selection stops when `none_other` wins at least half the trials
or has at least as much mean option mass as the top candidate.

Gradio exposes the generated API page and OpenAPI schema from the running Space.
The Hugging Face Space page also provides an `agents.md` integration guide.

## Run locally

```powershell
python -m pip install -r requirements.txt
$env:MERCURY_API_KEY = "..."
$env:TYPESAFE_API_KEY = "..."
python app.py
```

## Create a private Space

After the local files have been reviewed, authenticate with `hf auth login` and
run `python deploy_private.py`. The script reads the logged-in account name,
creates `sfumato-idea-engine` as a private Gradio Space, and uploads only the
four runtime files. It stops without uploading if that Space already exists.
Then add the two provider keys through the Space's Settings page. The deployment
script never reads or uploads those keys.

The endpoint uses sequential provider calls. A 100-candidate run takes longer
and costs more than the 33-candidate default. If a provider fails partway through,
the current prototype returns an error and does not persist a resumable run.
