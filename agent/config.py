"""Cau hinh doc tu bien moi truong (.env).

Khong bao gio viet thang API key vao code (Dieu 6 trong LUAT_GIT.md).
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

GOC_REPO = Path(__file__).resolve().parent.parent

# Nap file .env o goc repo neu co. .env nam trong .gitignore.
load_dotenv(GOC_REPO / ".env")

# Model mac dinh. Doi o .env bang bien MODEL neu can.
MODEL_MAC_DINH = "claude-opus-5"


@dataclass(frozen=True)
class CauHinh:
    api_key: str
    model: str
    max_tokens: int
    so_buoc_toi_da: int

    @staticmethod
    def tu_moi_truong() -> "CauHinh":
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError(
                "Thieu ANTHROPIC_API_KEY. Copy .env.example thanh .env roi dien key vao."
            )
        return CauHinh(
            api_key=api_key,
            model=os.environ.get("MODEL", MODEL_MAC_DINH),
            max_tokens=int(os.environ.get("MAX_TOKENS", "16000")),
            so_buoc_toi_da=int(os.environ.get("SO_BUOC_TOI_DA", "20")),
        )


def duong_dan_prompt(ten: str) -> Path:
    """Tra ve duong dan toi mot file prompt trong agent/prompts/."""
    return GOC_REPO / "agent" / "prompts" / ten


def doc_prompt(ten: str) -> str:
    return duong_dan_prompt(ten).read_text(encoding="utf-8")
