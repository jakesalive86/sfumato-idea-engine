"""Hosted Sfumato seed-packet pipeline.

This module is deliberately self-contained: a caller supplies a concrete,
mechanism-free problem brief and receives selected inspiration seeds. The
service does not interpret the user's conversation or run a final reasoner.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Callable


MERCURY_ENDPOINT = "https://api.inceptionlabs.ai/v1/chat/completions"
JEV_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MERCURY_MODEL = "mercury-2"
JEV_MODEL = "jev-1.13.0"
PROMPT_VERSION = "independent-seed-2026-09-23-v1"
RANKER_VERSION = "contrastive-jev-2026-09-23-v1"
MERCURY_INPUT_USD_PER_M = float(os.environ.get("SFUMATO_MERCURY_INPUT_USD_PER_M", "0.25"))
MERCURY_OUTPUT_USD_PER_M = float(os.environ.get("SFUMATO_MERCURY_OUTPUT_USD_PER_M", "0.75"))
JEV_INPUT_USD_PER_M = float(os.environ.get("SFUMATO_JEV_INPUT_USD_PER_M", "0.042"))
MAX_BRIEF_CHARS = 24_000
MAX_SEEDS = 5
MAX_TRIALS = 8
ALLOWED_COUNTS = {33, 100}

MERCURY_PROMPT = (
    "We need one inspiration seed for this problem.\n\n"
    "A reasoning model will later develop the seed. It is not required to be a "
    "complete or immediately feasible solution; preserve the generative thread "
    "instead of polishing it into a conventional answer. "
    "Favor an unusual mechanism, distant analogy, inverted assumption, or "
    "different framing. A rough but intelligible idea is valuable when it "
    "contains a recoverable conceptual thread.\n\n"
    "Return one candidate in a single paragraph of about {word_low}-{word_high} "
    "words, with an acceptable range of {word_low}-{word_high} words. State "
    "the central mechanism or analogy and the different direction it opens. "
    "End after the candidate is stated.\n\n"
    "Problem:\n{problem}"
)

RANK_CONTEXT = (
    "A capable reasoning model will later solve this problem. It tends to "
    "begin with familiar, high-probability approaches. These proposals are "
    "inspiration seeds, independently generated one per call. Prefer proposals "
    "that broaden the search through unexpected mechanisms, distant analogies, "
    "inverted assumptions, or different framings. A rough or partially formed "
    "proposal can be valuable when it contains a conceptual thread that can be "
    "developed. Judge the search direction it opens, not polish or immediate "
    "feasibility."
)

FIRST_QUESTION = (
    "Which proposal offers the most promising unusual direction for the "
    "reasoning model to explore and develop?"
)

NONE_OTHER = "No remaining proposal offers a promising unusual direction to explore."


class SfumatoError(RuntimeError):
    """A safe, user-displayable pipeline error."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_key(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SfumatoError(f"The Space owner has not configured the {name} secret.")
    return value


def _post_json(
    url: str,
    api_key: str,
    payload: dict[str, Any],
    *,
    timeout: float = 180.0,
    retries: int = 3,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    delay = 1.0
    last_status: int | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                decoded = json.loads(response.read().decode("utf-8"))
            if not isinstance(decoded, dict):
                raise SfumatoError("A provider returned an invalid response shape.")
            return decoded
        except urllib.error.HTTPError as exc:
            last_status = exc.code
            if exc.code not in (429, 529) or attempt + 1 == retries:
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt + 1 == retries:
                raise SfumatoError("A provider request failed. Please retry later.") from None
        time.sleep(delay)
        delay *= 2

    if last_status == 401:
        raise SfumatoError("A provider rejected its configured API key.")
    if last_status in (429, 529):
        raise SfumatoError("A provider is busy or rate limited. Please retry later.")
    if last_status is not None:
        raise SfumatoError(f"A provider request failed with HTTP {last_status}.")
    raise SfumatoError("A provider request failed. Please retry later.")


def validate_request(
    problem_brief: str,
    candidate_count: int,
    max_selected_seeds: int,
    trials_per_pass: int,
    word_range: list[int] | tuple[int, int] | None,
) -> tuple[str, tuple[int, int]]:
    if not isinstance(problem_brief, str):
        raise SfumatoError("problem_brief must be plain text.")
    brief = problem_brief.strip()
    if not brief:
        raise SfumatoError("Enter a concrete problem brief.")
    if len(brief) > MAX_BRIEF_CHARS:
        raise SfumatoError(f"The brief must be {MAX_BRIEF_CHARS:,} characters or fewer.")
    if type(candidate_count) is not int or candidate_count not in ALLOWED_COUNTS:
        raise SfumatoError("candidate_count must be 33 or 100.")
    if type(max_selected_seeds) is not int or not 1 <= max_selected_seeds <= MAX_SEEDS:
        raise SfumatoError(f"max_selected_seeds must be between 1 and {MAX_SEEDS}.")
    if type(trials_per_pass) is not int or trials_per_pass != MAX_TRIALS:
        raise SfumatoError(f"trials_per_pass is fixed at {MAX_TRIALS} for this release.")
    if word_range is None:
        words = (100, 180)
    elif (
        isinstance(word_range, (list, tuple))
        and len(word_range) == 2
        and all(isinstance(item, int) for item in word_range)
    ):
        words = (word_range[0], word_range[1])
    else:
        raise SfumatoError("word_range must contain [minimum_words, maximum_words].")
    low, high = words
    if low < 50 or high > 250 or low >= high:
        raise SfumatoError("word_range must satisfy 50 <= minimum < maximum <= 250.")
    return brief, words


def _candidate_prompt(problem_brief: str, word_range: tuple[int, int]) -> str:
    return MERCURY_PROMPT.format(
        word_low=word_range[0], word_high=word_range[1], problem=problem_brief
    )


def _generate_one(
    problem_brief: str,
    candidate_id: int,
    api_key: str,
    word_range: tuple[int, int],
) -> dict[str, Any]:
    response = _post_json(
        MERCURY_ENDPOINT,
        api_key,
        {
            "model": MERCURY_MODEL,
            "messages": [{"role": "user", "content": _candidate_prompt(problem_brief, word_range)}],
            "max_tokens": 256,
            "temperature": 1.0,
            "reasoning_effort": "low",
        },
    )
    try:
        text = response["choices"][0]["message"].get("content", "").strip()
    except (KeyError, IndexError, AttributeError, TypeError):
        text = ""
    if not text:
        raise SfumatoError(f"Mercury returned an empty candidate at position {candidate_id}.")
    usage = response.get("usage") or {}
    if not isinstance(usage, dict):
        usage = {}
    return {
        "candidate_id": candidate_id,
        "text": text,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "warning": response.get("warning"),
    }


def _choice_call(
    api_key: str,
    state: dict[str, str],
    criteria: dict[str, str],
    question: str,
) -> tuple[dict[str, float], str | None, int]:
    response = _post_json(
        JEV_ENDPOINT,
        api_key,
        {
            "model": JEV_MODEL,
            "state": state,
            "questions": {
                "selection": {
                    "type": "choice",
                    "instructions": question,
                    "criteria": criteria,
                }
            },
        },
        timeout=45,
    )
    try:
        answer = response["answers"]["selection"]
    except (KeyError, TypeError):
        raise SfumatoError("Jev returned an invalid selection response.") from None
    probabilities = answer.get("probabilities") or {}
    if not isinstance(probabilities, dict):
        probabilities = {}
    mass = {key: float(probabilities.get(key, 0.0)) for key in criteria}
    picked = answer.get("choice")
    usage = response.get("usage") or {}
    input_tokens = usage.get("input_tokens", 0) if isinstance(usage, dict) else 0
    try:
        token_count = max(0, int(input_tokens))
    except (TypeError, ValueError):
        token_count = 0
    return mass, picked if isinstance(picked, str) else None, token_count


def _rank_pass(
    *,
    candidates: list[dict[str, Any]],
    selected: list[dict[str, Any]],
    problem_brief: str,
    api_key: str,
    trials: int,
    seed: int,
) -> dict[str, Any]:
    rng = random.Random(seed)
    values: dict[str, list[float]] = defaultdict(list)
    winners: list[str] = []
    order_flips = 0
    jev_input_tokens = 0
    selected_text = "\n\n".join(
        f"Selected branch {index}: {item['text']}"
        for index, item in enumerate(selected, 1)
    )
    context = RANK_CONTEXT.replace(
        "These proposals", f"These {len(candidates)} remaining proposals"
    )
    if selected:
        context += (
            "\n\nThe following branches have already been selected:\n"
            + selected_text
            + "\n\nChoose a remaining proposal with a substantively different "
            "underlying mechanism, causal story, or conceptual framing. Do not "
            "select a paraphrase or minor variation of an already selected branch. "
            "Preserve relevance while maximizing inventive separation."
        )
        question = (
            "Which remaining proposal should receive attention next because it "
            "opens the strongest relevant search direction that is substantively "
            "different from every branch already selected?"
        )
    else:
        question = FIRST_QUESTION

    state = {"problem": problem_brief, "selection_purpose": context}
    for _trial in range(trials):
        shuffled = list(candidates)
        rng.shuffle(shuffled)
        label_to_id = {
            f"candidate_{index:03d}": row["candidate_id"]
            for index, row in enumerate(shuffled, 1)
        }
        criteria = {
            label: next(row["text"] for row in shuffled if row["candidate_id"] == candidate_id)
            for label, candidate_id in label_to_id.items()
        }
        criteria["none_other"] = NONE_OTHER
        first_mass, first_choice, first_tokens = _choice_call(
            api_key, state, criteria, question
        )
        reversed_criteria = dict(reversed(list(criteria.items())))
        second_mass, second_choice, second_tokens = _choice_call(
            api_key, state, reversed_criteria, question
        )
        jev_input_tokens += first_tokens + second_tokens
        if first_choice != second_choice:
            order_flips += 1
        winner = label_to_id.get(first_choice, "none_other")
        winners.append(winner)
        for label, candidate_id in label_to_id.items():
            values[candidate_id].append(
                (first_mass.get(label, 0.0) + second_mass.get(label, 0.0)) / 2.0
            )
        values["none_other"].append(
            (first_mass.get("none_other", 0.0) + second_mass.get("none_other", 0.0)) / 2.0
        )

    by_id = {row["candidate_id"]: row for row in candidates}
    ranked = []
    for candidate_id, masses in values.items():
        if candidate_id == "none_other":
            continue
        mean_mass = sum(masses) / len(masses) if masses else 0.0
        variance = sum((value - mean_mass) ** 2 for value in masses) / len(masses)
        ranked.append(
            {
                **by_id[candidate_id],
                "mean_mass": mean_mass,
                "mass_sd": variance ** 0.5,
                "wins": winners.count(candidate_id),
            }
        )
    ranked.sort(key=lambda row: (-row["mean_mass"], row["candidate_id"]))
    none_masses = values.get("none_other", [])
    return {
        "ranked": ranked,
        "winners": winners,
        "winner_counts": dict(Counter(winners)),
        "none_other_mean_mass": sum(none_masses) / len(none_masses) if none_masses else 0.0,
        "order_flips": order_flips,
        "jev_input_tokens": jev_input_tokens,
    }


def _select(
    candidates: list[dict[str, Any]],
    *,
    problem_brief: str,
    api_key: str,
    max_selected_seeds: int,
    trials: int,
    seed: int,
    progress: Callable[[float, str], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    remaining = list(candidates)
    selected: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    total_jev_tokens = 0
    stop_reason = "maximum_selection_passes_reached"
    stop_pass: int | None = None

    for pass_number in range(1, max_selected_seeds + 1):
        if not remaining:
            stop_reason = "no_candidates_remaining"
            stop_pass = pass_number
            break
        if progress:
            progress(0.30 + 0.65 * ((pass_number - 1) / max_selected_seeds),
                     f"Jev selection pass {pass_number}/{max_selected_seeds}")
        ranked_pass = _rank_pass(
            candidates=remaining,
            selected=selected,
            problem_brief=problem_brief,
            api_key=api_key,
            trials=trials,
            seed=seed + pass_number,
        )
        ranked = ranked_pass["ranked"]
        if not ranked:
            stop_reason = "no_candidates_ranked"
            stop_pass = pass_number
            break
        best = ranked[0]
        none_mass = ranked_pass["none_other_mean_mass"]
        none_wins = ranked_pass["winner_counts"].get("none_other", 0)
        best_wins = int(best["wins"])
        total_jev_tokens += ranked_pass["jev_input_tokens"]

        if none_wins >= (trials / 2):
            stop_reason = "none_other_won_at_least_half"
            stop_pass = pass_number
        elif none_mass >= best["mean_mass"]:
            stop_reason = "none_other_mass_at_least_best_candidate"
            stop_pass = pass_number
        elif best_wins < 3:
            decisions.append(
                {
                    "pass": pass_number,
                    "candidate_id": best["candidate_id"],
                    "decision": "skip_unresolved",
                    "status": "unresolved",
                    "reason": "best_candidate_won_fewer_than_three_trials",
                    "winner_count": best_wins,
                    "trial_count": trials,
                    "none_other_wins": none_wins,
                    "candidate_mass": best["mean_mass"],
                    "none_other_mass": none_mass,
                    "order_flips": ranked_pass["order_flips"],
                }
            )
            remaining = [row for row in remaining if row["candidate_id"] != best["candidate_id"]]
            continue
        if stop_pass is not None:
            decisions.append(
                {
                    "pass": pass_number,
                    "candidate_id": best["candidate_id"],
                    "decision": "stop",
                    "reason": stop_reason,
                    "winner_count": best_wins,
                    "trial_count": trials,
                    "none_other_wins": none_wins,
                    "candidate_mass": best["mean_mass"],
                    "none_other_mass": none_mass,
                    "order_flips": ranked_pass["order_flips"],
                }
            )
            break

        if best_wins >= 6:
            status = "core"
        elif best_wins >= 4:
            status = "optional"
        else:
            status = "unresolved"

        decision = {
            "pass": pass_number,
            "candidate_id": best["candidate_id"],
            "decision": "selected" if status != "unresolved" else "skip_unresolved",
            "status": status,
            "winner_count": best_wins,
            "trial_count": trials,
            "none_other_wins": none_wins,
            "candidate_mass": best["mean_mass"],
            "none_other_mass": none_mass,
            "order_flips": ranked_pass["order_flips"],
        }
        decisions.append(decision)
        best_record = {
            "rank": len(selected) + 1,
            "candidate_id": best["candidate_id"],
            "text": best["text"],
            "status": status,
            "winner_count": best_wins,
            "trial_count": trials,
            "candidate_mass": best["mean_mass"],
            "candidate_mass_sd": best["mass_sd"],
            "none_other_mass": none_mass,
            "none_other_wins": none_wins,
            "order_flips": ranked_pass["order_flips"],
            "candidate_sha256": best["sha256"],
        }
        if status != "unresolved":
            selected.append(best_record)
        remaining = [row for row in remaining if row["candidate_id"] != best["candidate_id"]]

    if stop_pass is None:
        stop_pass = max_selected_seeds
    return selected, {
        "reason": stop_reason,
        "pass": stop_pass,
        "decisions": decisions,
    }, total_jev_tokens


def generate_seed_packet(
    problem_brief: str,
    *,
    candidate_count: int = 33,
    max_selected_seeds: int = 5,
    trials_per_pass: int = 8,
    word_range: list[int] | tuple[int, int] | None = None,
    client_run_id: str | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    if client_run_id is not None and (
        not isinstance(client_run_id, str) or len(client_run_id) > 128
    ):
        raise SfumatoError("client_run_id must be text no longer than 128 characters.")
    brief, word_limits = validate_request(
        problem_brief, candidate_count, max_selected_seeds, trials_per_pass, word_range
    )
    mercury_key = _require_key("MERCURY_API_KEY")
    jev_key = _require_key("TYPESAFE_API_KEY")
    run_id = str(uuid.uuid4())
    seed = int.from_bytes(os.urandom(8), "big") % (2**31 - 1)
    candidates = []
    warnings: list[str] = []
    mercury_input = 0
    mercury_output = 0
    mercury_usage_known = True

    for index in range(1, candidate_count + 1):
        if progress:
            progress(0.30 * ((index - 1) / candidate_count),
                     f"Mercury candidate {index}/{candidate_count}")
        candidate = _generate_one(brief, index, mercury_key, word_limits)
        if isinstance(candidate["input_tokens"], int):
            mercury_input += candidate["input_tokens"]
        else:
            mercury_usage_known = False
        if isinstance(candidate["output_tokens"], int):
            mercury_output += candidate["output_tokens"]
        else:
            mercury_usage_known = False
        if candidate["warning"]:
            warnings.append(f"Mercury: {str(candidate['warning'])[:300]}")
        candidates.append(candidate)

    if progress:
        progress(0.30, "Mercury generation complete; ranking distinct directions")
    selected, stop, jev_tokens = _select(
        candidates,
        problem_brief=brief,
        api_key=jev_key,
        max_selected_seeds=max_selected_seeds,
        trials=trials_per_pass,
        seed=seed,
        progress=progress,
    )
    mercury_cost = None
    jev_cost = jev_tokens * JEV_INPUT_USD_PER_M / 1_000_000
    if mercury_usage_known:
        mercury_cost = (
            mercury_input * MERCURY_INPUT_USD_PER_M
            + mercury_output * MERCURY_OUTPUT_USD_PER_M
        ) / 1_000_000
    else:
        warnings.append("Mercury did not return complete token usage; its cost is unknown.")
    total_cost = None if mercury_cost is None else mercury_cost + jev_cost
    if any(item["status"] == "optional" for item in selected):
        warnings.append("Optional seeds have weaker selection support than core seeds.")
    if any(item["decision"] == "skip_unresolved" for item in stop["decisions"]):
        warnings.append("At least one unstable candidate was skipped; selection continued.")

    return {
        "schema": "sfumato-seed-packet-1",
        "run_id": run_id,
        "client_run_id": client_run_id,
        "problem_brief": brief,
        "generator": {
            "provider": "inception",
            "model": MERCURY_MODEL,
            "candidate_count_requested": candidate_count,
            "candidate_count_returned": len(candidates),
            "independent_calls": True,
            "word_range": list(word_limits),
        },
        "ranker": {"provider": "typesafe", "model": JEV_MODEL, "trials_per_pass": trials_per_pass},
        "selected_seeds": selected,
        "stop": stop,
        "usage": {
            "mercury_input_tokens": mercury_input if mercury_usage_known else None,
            "mercury_output_tokens": mercury_output if mercury_usage_known else None,
            "jev_input_tokens": jev_tokens,
            "mercury_estimated_cost_usd": mercury_cost,
            "jev_estimated_cost_usd": jev_cost,
            "estimated_cost_usd": total_cost,
            "pricing_usd_per_million": {
                "mercury_input": MERCURY_INPUT_USD_PER_M,
                "mercury_output": MERCURY_OUTPUT_USD_PER_M,
                "jev_input": JEV_INPUT_USD_PER_M,
                "jev_output": 0.0,
            },
        },
        "warnings": warnings,
        "provenance": {
            "created_at": _utc_now(),
            "prompt_version": PROMPT_VERSION,
            "ranker_version": RANKER_VERSION,
            "selection_seed": seed,
            "candidate_hashes": [row["sha256"] for row in candidates],
            "candidate_count": len(candidates),
        },
    }
