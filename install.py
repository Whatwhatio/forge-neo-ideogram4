from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ENV_DIR = ROOT / "env"
REFERENCE_DIR = ROOT / "official_source"
REQUIRED_IMPORTS = (
    "import torch; "
    "assert tuple(map(int, torch.__version__.split('+')[0].split('.')[:2])) >= (2, 11); "
    "import accelerate, bitsandbytes, einops, huggingface_hub, PIL, requests, "
    "safetensors, sentencepiece, transformers"
)


def run(*args: str) -> None:
    print("[Ideogram 4]", " ".join(args), flush=True)
    subprocess.check_call(args)


def environment_ready(python: Path) -> bool:
    result = subprocess.run(
        [str(python), "-c", REQUIRED_IMPORTS],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def main() -> None:
    if not REFERENCE_DIR.exists():
        raise SystemExit(
            f"Missing official Ideogram source at {REFERENCE_DIR}. "
            "Clone https://github.com/ideogram-oss/ideogram4 into "
            "`official_source` first."
        )

    if not ENV_DIR.exists():
        run(sys.executable, "-m", "venv", str(ENV_DIR))

    python = ENV_DIR / "Scripts" / "python.exe"
    if environment_ready(python):
        print("[Ideogram 4] Isolated environment is ready.", flush=True)
        return

    run(str(python), "-m", "pip", "install", "--upgrade", "pip", "wheel")
    run(
        str(python),
        "-m",
        "pip",
        "install",
        "--upgrade",
        "torch>=2.11",
        "--index-url",
        "https://download.pytorch.org/whl/cu130",
    )
    run(
        str(python),
        "-m",
        "pip",
        "install",
        "transformers>=4.49.0",
        "safetensors>=0.4.5",
        "accelerate>=1.0.0",
        "einops>=0.7.0",
        "sentencepiece",
        "pillow",
        "huggingface_hub>=0.26.0",
        "requests>=2.28",
        "bitsandbytes>=0.49.2",
    )
    if not environment_ready(python):
        raise SystemExit("Ideogram 4 environment validation failed after installation.")


if __name__ == "__main__":
    main()
