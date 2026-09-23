"""Gradio UI and API for the Sfumato inspiration-seed service."""

from __future__ import annotations

import gradio as gr

from sfumato_core import SfumatoError, generate_seed_packet


def run_pipeline(
    problem_brief: str,
    candidate_count: int,
    max_selected_seeds: int,
    trials_per_pass: int,
    word_range: list[int],
    client_run_id: str,
    progress=gr.Progress(track_tqdm=False),
) -> dict:
    try:
        return generate_seed_packet(
            problem_brief,
            candidate_count=int(candidate_count),
            max_selected_seeds=int(max_selected_seeds),
            trials_per_pass=int(trials_per_pass),
            word_range=word_range,
            client_run_id=client_run_id or None,
            progress=lambda value, description: progress(value, desc=description),
        )
    except SfumatoError as exc:
        raise gr.Error(str(exc), duration=10) from None


with gr.Blocks(title="Sfumato Idea Engine") as demo:
    gr.Markdown(
        """# Sfumato Idea Engine

Turn a concrete problem brief into a ranked packet of unusual inspiration seeds. """
    )
    with gr.Row():
        with gr.Column(scale=2):
            problem_brief = gr.Textbox(
                label="Problem brief",
                placeholder=(
                    "Describe the situation, objective, success condition, constraints, "
                    "and exclusions. Leave proposed mechanisms open."
                ),
                lines=12,
                max_lines=24,
            )
            with gr.Row():
                candidate_count = gr.Radio(
                    choices=[33, 100], value=33, label="Independent candidates"
                )
                max_selected_seeds = gr.Slider(
                    minimum=1, maximum=5, step=1, value=5, label="Maximum selection passes"
                )
            trials_per_pass = gr.Radio(
                choices=[8], value=8, label="Jev trials per pass (fixed)"
            )
            word_range = gr.JSON(
                value=[100, 180], label="Candidate word range [minimum, maximum]"
            )
            client_run_id = gr.Textbox(
                label="Optional caller run ID", placeholder="e.g. project-2026-09-23"
            )
            run_button = gr.Button("Generate inspiration seeds", variant="primary")
        with gr.Column(scale=3):
            result = gr.JSON(label="Seed packet")

    gr.Markdown(
        """Each candidate is generated in a separate Mercury call. Jev ranks the
        pool through shuffled, order-debiased trials. Scores guide attention; they
        are not calibrated probabilities. The final reasoning model is chosen by
        the caller and is not part of this service.

        The Space owner pays provider charges. Keep the Space private during the
        funded prototype; public use should use a duplicated Space with the user's
        own provider keys."""
    )

    run_button.click(
        fn=run_pipeline,
        inputs=[
            problem_brief,
            candidate_count,
            max_selected_seeds,
            trials_per_pass,
            word_range,
            client_run_id,
        ],
        outputs=result,
        api_name="generate_seed_packet",
        concurrency_limit=1,
        show_progress="full",
    )


demo.queue(default_concurrency_limit=1, max_size=10)


if __name__ == "__main__":
    demo.launch(show_error=False)
