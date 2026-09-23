---
name: sfumato
description: Generate independent, unusual inspiration seeds through the Sfumato API, then help the active reasoning model credit, rank, and coalesce the ideas without forcing one answer.
---

# Sfumato

Use Sfumato when the user wants new directions, mechanisms, or options and a
single direct answer is not enough. The service creates and ranks inspiration
seeds. The currently active reasoning model does the interpretive work; do not
select or call a separate final reasoner.

## Request a seed packet

1. Write a concrete, mechanism-free brief from the user's request and available
   context. State the objective, situation, success condition, constraints, and
   exclusions. Keep the proposed solution open. Ask a short clarification only
   when a missing fact would materially change the search.
2. Use 33 candidates by default. Use 100 only when the user asks for a broad,
   higher-cost run. The Space owner pays for Mercury and Jev calls.
3. Call the configured Space with the helper:

   Install the helper dependency once with `python -m pip install gradio_client`,
   then run `python "<skill-directory>\scripts\request_seed_packet.py" --space <namespace/space-name> --brief-file <path-to-brief.txt> --candidate-count 33`.

   `HF_TOKEN` is needed for a private Space. The helper writes only the returned
   JSON packet to standard output. Do not provide Mercury or Jev keys to this
   helper; they belong in the Space's owner-managed Secrets.
4. Read the full packet. Tell the user the candidate count, how many seeds
   survived selection, the stop reason, any warnings, and the estimated cost.
   Jev option mass and win counts order attention; they are not correctness
   probabilities.

## Harvest seeds with the active reasoner

Use the returned seeds in their given order. Keep each `candidate_id` attached
to every note and conclusion so the user can trace an insight to its seed.
For each seed:

1. Translate its mechanism into plain language before judging it.
2. State what would have to be true for it to work.
3. Separate impossible from merely unbuilt. Continue reasoning from a failed
   implementation if it reveals a useful underlying idea.
4. Record the surviving contribution, the main weakness, and its disposition:
   develop, combine, park, or set aside.

Do not merge seeds just because they address the same topic. Combine only when
their causal mechanisms reinforce one another. Preserve standalone alternatives
and provenance when they do not combine. Do not turn an option-generation task
into a single polished solution unless the user asks for that next step.

## Close the exploration

Return an **Idea Credit Ledger** with one row per delivered seed, ordered by
idea value. Include the candidate ID, surviving contribution, idea value (1–5),
immediate solution value (1–5), and disposition. These are separate judgements:
a speculative idea can be valuable even when it is not a workable solution now.

Then provide **Coalescence Decisions**: which seed IDs combine, the shared
causal mechanism that supports each combination, and which ideas remain
standalone. Finish with a concise synthesis of the most promising directions;
keep material distinctions visible.

If the Space is unavailable, credentials are missing, or the call fails, report
that plainly. Do not present an ordinary brainstorm as though it came from the
independent generation and ranking process.
