from __future__ import annotations

import json
import os
import secrets
import sys
import traceback
from datetime import datetime
from multiprocessing.connection import Listener
from pathlib import Path
from PIL import PngImagePlugin


ROOT = Path(__file__).resolve().parent
OFFICIAL_SOURCE = ROOT / "official_source" / "src"
sys.path.insert(0, str(OFFICIAL_SOURCE))

PIPE = None
PIPE_REPO = None
ADDRESS = ("127.0.0.1", 17861)
AUTHKEY = b"forge-ideogram4-local"
LOG_PATH = ROOT / "worker.log"
PROGRESS_SINK = None
LOG_SINK = None


def log(message: str, publish: bool = True) -> None:
    global LOG_SINK
    line = f"[Ideogram 4 {datetime.now():%H:%M:%S}] {message}"
    print(line, flush=True)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
    if publish and LOG_SINK is not None:
        try:
            LOG_SINK(line)
        except (BrokenPipeError, EOFError, OSError):
            LOG_SINK = None


def progress(stage: str, current: int, total: int) -> None:
    global PROGRESS_SINK
    if total > 1:
        log(f"{stage}: {current}/{total} ({current / total:.0%})", publish=False)
    elif current:
        log(f"{stage}: complete", publish=False)
    else:
        log(f"{stage}...", publish=False)
    if PROGRESS_SINK is not None:
        try:
            PROGRESS_SINK(stage, current, total)
        except (BrokenPipeError, EOFError, OSError):
            PROGRESS_SINK = None


def gated_repo_message(repo: str, token_supplied: bool) -> str:
    if token_supplied:
        action = (
            "A Hugging Face token was supplied. Verify that it is correct, has "
            "read access, belongs to the account granted access to this model, "
            "and that you accepted the model's license."
        )
    else:
        action = (
            "No Hugging Face token was supplied. Enter a Hugging Face read token "
            "in the Ideogram 4 tab after accepting the model's license."
        )
    return (
        f"Cannot access gated repository {repo}. Access is restricted and "
        f"authentication is required. {action}"
    )


def load_pipeline(repo: str, hf_token: str = ""):
    global PIPE, PIPE_REPO
    if PIPE is not None and PIPE_REPO == repo:
        log(f"Model already loaded: {repo}")
        return PIPE

    if hf_token:
        os.environ["HF_TOKEN"] = hf_token
    unload()
    log(f"Loading model: {repo}")
    log("Hugging Face will show byte progress below for any uncached files.")
    import torch
    from ideogram4 import Ideogram4Pipeline, Ideogram4PipelineConfig
    from huggingface_hub.errors import GatedRepoError

    try:
        PIPE = Ideogram4Pipeline.from_pretrained(
            config=Ideogram4PipelineConfig(weights_repo=repo),
            device="cuda",
            dtype=torch.bfloat16,
            progress_callback=progress,
        )
    except GatedRepoError as exc:
        message = gated_repo_message(repo, bool(hf_token))
        log(f"Hugging Face error: {exc}")
        log(message)
        raise RuntimeError(message) from exc
    PIPE_REPO = repo
    log("Model loaded into RAM/VRAM.")
    return PIPE


def unload() -> None:
    global PIPE, PIPE_REPO
    if PIPE is not None:
        log("Unloading model from RAM/VRAM...")
        del PIPE
        PIPE = None
        PIPE_REPO = None
        try:
            import gc
            import torch

            gc.collect()
            torch.cuda.empty_cache()
        except Exception:
            pass
        log("Model unloaded.")


def expand_prompt(prompt: str, width: int, height: int, api_key: str) -> str:
    if not api_key:
        return prompt

    from ideogram4 import MAGIC_PROMPTS, aspect_ratio_from_size

    magic = MAGIC_PROMPTS["ideogram-4-v1"](api_key=api_key)
    return magic.expand(prompt, aspect_ratio=aspect_ratio_from_size(width, height))


def inference_prompt(prompt: str) -> str:
    """Remove Forge-only display fields from structured Ideogram captions."""
    try:
        parsed = json.loads(prompt)
    except (json.JSONDecodeError, TypeError):
        return prompt

    captions = parsed if isinstance(parsed, list) else [parsed]
    for caption in captions:
        if not isinstance(caption, dict):
            continue
        composition = caption.get("compositional_deconstruction")
        if not isinstance(composition, dict):
            continue
        elements = composition.get("elements")
        if not isinstance(elements, list):
            continue
        for element in elements:
            if isinstance(element, dict):
                element.pop("box_color", None)
                element.pop("color", None)
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def build_png_metadata(
    prompt: str,
    repo: str,
    preset_name: str,
    num_steps: int,
    width: int,
    height: int,
    seed: int,
) -> PngImagePlugin.PngInfo:
    settings = {
        "caption": prompt,
        "model": repo,
        "preset": preset_name,
        "steps": num_steps,
        "width": width,
        "height": height,
        "seed": seed,
    }
    parameters = (
        f"{prompt}\n"
        f"Steps: {num_steps}, Sampler: {preset_name}, Seed: {seed}, "
        f"Size: {width}x{height}, Model: {repo}, Generator: Ideogram 4 NF4"
    )
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("parameters", parameters)
    metadata.add_text("ideogram4_caption", prompt)
    metadata.add_text(
        "ideogram4_settings",
        json.dumps(settings, ensure_ascii=False, separators=(",", ":")),
    )
    metadata.add_text("Software", "Forge Neo Ideogram 4 extension")
    return metadata


def generate(message: dict) -> dict:
    from ideogram4 import PRESETS

    repo = message.get("repo") or "ideogram-ai/ideogram-4-nf4"
    width = int(message.get("width") or 1024)
    height = int(message.get("height") or 1024)
    seed = int(message.get("seed") or 0)
    if seed < 0:
        seed = secrets.randbelow(2**32)
        log(f"Random seed selected: {seed}")
    preset_name = message.get("preset") or "V4_DEFAULT_20"
    prompt = str(message.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("Prompt is empty.")

    prompt = expand_prompt(
        prompt,
        width,
        height,
        str(message.get("magic_prompt_key") or "").strip(),
    )
    preset = PRESETS[preset_name]
    pipe = load_pipeline(repo, str(message.get("hf_token") or "").strip())
    log(
        f"Generating {width}x{height}, preset {preset_name}, "
        f"{preset.num_steps} steps, seed {seed}."
    )
    images = pipe(
        inference_prompt(prompt),
        height=height,
        width=width,
        num_steps=preset.num_steps,
        guidance_schedule=preset.guidance_schedule,
        mu=preset.mu,
        std=preset.std,
        seed=seed,
        raise_on_caption_issues=not bool(message.get("allow_caption_warnings", True)),
        progress_callback=progress,
    )

    output_dir = Path(message["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output = output_dir / f"ideogram4-{stamp}-seed-{seed}.png"
    metadata = build_png_metadata(
        prompt,
        repo,
        preset_name,
        preset.num_steps,
        width,
        height,
        seed,
    )
    images[0].save(output, pnginfo=metadata)
    log(f"Saved image: {output}")
    return {
        "ok": True,
        "image": str(output),
        "caption": prompt,
        "message": f"Generated with {preset_name} at {width}x{height}, seed {seed}.",
    }


def handle(message: dict) -> dict:
    action = message.get("action")
    if action == "ping":
        import bitsandbytes
        import torch
        import transformers

        return {
            "ok": True,
            "message": (
                f"Ready: torch {torch.__version__}, CUDA {torch.version.cuda}, "
                f"transformers {transformers.__version__}, "
                f"bitsandbytes {bitsandbytes.__version__}"
            ),
        }
    if action == "load":
        load_pipeline(
            message.get("repo") or "ideogram-ai/ideogram-4-nf4",
            str(message.get("hf_token") or "").strip(),
        )
        return {"ok": True, "message": "Ideogram 4 is loaded."}
    if action == "unload":
        unload()
        return {"ok": True, "message": "Ideogram 4 was unloaded from VRAM."}
    if action == "generate":
        return generate(message)
    raise ValueError(f"Unknown action: {action}")


with Listener(ADDRESS, authkey=AUTHKEY) as listener:
    log(f"Worker ready on {ADDRESS[0]}:{ADDRESS[1]}.")
    while True:
        with listener.accept() as connection:
            try:
                request = connection.recv()
                PROGRESS_SINK = lambda stage, current, total: connection.send({
                    "event": "progress",
                    "stage": stage,
                    "current": current,
                    "total": total,
                })
                LOG_SINK = lambda line: connection.send({
                    "event": "log",
                    "message": line,
                })
                connection.send({
                    "event": "result",
                    "response": handle(request),
                })
            except Exception as exc:
                log(f"Request failed: {exc}")
                try:
                    connection.send({
                        "event": "result",
                        "response": {
                            "ok": False,
                            "error": str(exc),
                            "traceback": traceback.format_exc(),
                        },
                    })
                except (BrokenPipeError, EOFError, OSError):
                    pass
            finally:
                PROGRESS_SINK = None
                LOG_SINK = None
