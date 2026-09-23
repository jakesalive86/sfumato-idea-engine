"""Create a new private Sfumato Space and upload only its runtime files."""

from __future__ import annotations

from pathlib import Path

from huggingface_hub import HfApi


SPACE_NAME = "sfumato-idea-engine"
UPLOAD_FILES = ["README.md", "app.py", "sfumato_core.py", "requirements.txt"]


def main() -> int:
    api = HfApi()
    try:
        account = api.whoami()
    except Exception as exc:  # noqa: BLE001 - provider error may include auth details
        print(f"Hugging Face authentication is unavailable ({type(exc).__name__}).")
        print("Run `hf auth login`, then retry this command.")
        return 2

    username = account.get("name")
    if not username:
        print("Hugging Face did not return the authenticated username.")
        return 2
    repo_id = f"{username}/{SPACE_NAME}"

    try:
        if api.repo_exists(repo_id, repo_type="space"):
            print(f"Space already exists at https://huggingface.co/spaces/{repo_id}.")
            print("No files were uploaded. Inspect the existing Space before updating it.")
            return 2
        api.create_repo(
            repo_id=repo_id,
            repo_type="space",
            space_sdk="gradio",
            private=True,
        )
        api.upload_folder(
            repo_id=repo_id,
            repo_type="space",
            folder_path=Path(__file__).resolve().parent,
            allow_patterns=UPLOAD_FILES,
            commit_message="Create private Sfumato Idea Engine Space",
        )
    except Exception as exc:  # noqa: BLE001 - do not print remote error bodies
        print(f"Private Space deployment failed ({type(exc).__name__}).")
        print("Check the HF CLI login and Space creation permissions, then inspect the Hub.")
        return 1

    print(f"Created private Space: https://huggingface.co/spaces/{repo_id}")
    print("Add MERCURY_API_KEY and TYPESAFE_API_KEY as Space Secrets in its Settings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
