"""Configuration loaded from environment variables (.env).

Never write an API key straight into the code; keep it in .env, which is gitignored.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

# Load .env from the repo root if present. .env is gitignored.
load_dotenv(REPO_ROOT / ".env")

# Default model. Override with MODEL in .env.
DEFAULT_MODEL = "claude-opus-5"


@dataclass(frozen=True)
class Config:
    api_key: str
    model: str
    max_tokens: int
    max_steps: int

    @staticmethod
    def from_env() -> "Config":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "Thiếu ANTHROPIC_API_KEY. Copy .env.example thành .env rồi điền key vào."
            )
        return Config(
            api_key=api_key,
            model=os.environ.get("MODEL", DEFAULT_MODEL),
            max_tokens=int(os.environ.get("MAX_TOKENS", "16000")),
            max_steps=int(os.environ.get("MAX_STEPS", "20")),
        )


def prompt_path(name: str) -> Path:
    """Return the path to a prompt file in agent/prompts/."""
    return REPO_ROOT / "agent" / "prompts" / name


def read_prompt(name: str) -> str:
    return prompt_path(name).read_text(encoding="utf-8")
