from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from collections import OrderedDict
from multiprocessing.connection import Client
from pathlib import Path

import gradio as gr

from modules import script_callbacks


ROOT = Path(__file__).resolve().parents[1]
ENV_PYTHON = ROOT / "env" / "Scripts" / "python.exe"
WORKER = ROOT / "worker.py"
OUTPUT_DIR = ROOT.parent.parent / "outputs" / "ideogram4"
LOG_PATH = ROOT / "worker.log"
LAST_SETTINGS_PATH = ROOT / "last_settings.json"
ADDRESS = ("127.0.0.1", 17861)
AUTHKEY = b"forge-ideogram4-local"
_LOCK = threading.Lock()
_PROCESS = None
_LOG_HANDLE = None


def _start_worker():
    global _PROCESS, _LOG_HANDLE
    if _PROCESS is not None and _PROCESS.poll() is None:
        return _PROCESS
    if not ENV_PYTHON.exists():
        raise RuntimeError(
            "Ideogram environment is not installed. Run "
            f"`{ROOT / 'setup.bat'}` once, then restart Forge Neo."
        )

    print("[Ideogram 4] Starting isolated worker...", flush=True)
    _PROCESS = subprocess.Popen(
        [str(ENV_PYTHON), "-u", str(WORKER)],
        stdin=subprocess.DEVNULL,
    )
    for _ in range(100):
        if _PROCESS.poll() is not None:
            raise RuntimeError(
                f"Ideogram worker failed to start. See {LOG_PATH}."
            )
        try:
            with Client(ADDRESS, authkey=AUTHKEY) as connection:
                connection.send({"action": "ping"})
                connection.recv()
            break
        except (ConnectionRefusedError, FileNotFoundError):
            time.sleep(0.1)
    else:
        raise RuntimeError(f"Ideogram worker did not become ready. See {LOG_PATH}.")
    return _PROCESS


def _request(payload, progress=None):
    with _LOCK:
        _start_worker()
        with Client(ADDRESS, authkey=AUTHKEY) as connection:
            connection.send(payload)
            while True:
                message = connection.recv()
                if message.get("event") == "log":
                    if progress is not None:
                        progress(0, desc=str(message.get("message") or "Working..."))
                    continue
                if message.get("event") == "progress":
                    current = int(message.get("current") or 0)
                    total = max(1, int(message.get("total") or 1))
                    stage = str(message.get("stage") or "Working")
                    if progress is not None:
                        if total > 1:
                            description = (
                                f"{stage.title()}: {current}/{total} "
                                f"({current / total:.0%})"
                            )
                            progress((current, total), desc=description)
                        else:
                            description = (
                                f"{stage.title()}: complete"
                                if current else f"{stage.title()}..."
                            )
                            progress(current, desc=description)
                    continue
                if message.get("event") == "result":
                    response = message["response"]
                else:
                    # Compatibility with a worker started before this update.
                    response = message
                break
        if not response.get("ok"):
            raise RuntimeError(
                response.get("error", "Ideogram worker failed")
                + "\n\n"
                + response.get("traceback", "")
            )
        return response


def check_environment():
    try:
        return _request({"action": "ping"})["message"]
    except Exception as exc:
        return f"Environment check failed:\n\n```\n{exc}\n```"


def load_model(repo, hf_token, progress=gr.Progress()):
    try:
        return _request({
            "action": "load",
            "repo": repo,
            "hf_token": hf_token,
        }, progress=progress)["message"]
    except Exception as exc:
        return f"Load failed:\n\n```\n{exc}\n```"


def unload_model():
    try:
        return _request({"action": "unload"})["message"]
    except Exception as exc:
        return f"Unload failed:\n\n```\n{exc}\n```"


def _palette(value, limit):
    colors = []
    if isinstance(value, list):
        raw_values = value
    else:
        raw_values = (value or "").replace(",", " ").split()
    for raw in raw_values:
        color = str(raw or "").strip().upper()
        if color and not color.startswith("#"):
            color = "#" + color
        if len(color) == 7 and all(c in "0123456789ABCDEF" for c in color[1:]):
            colors.append(color)
    return colors[:limit]


def _duplicates_background(description, background, bbox):
    if not (isinstance(bbox, list) and len(bbox) == 4):
        return False
    ymin, xmin, ymax, xmax = bbox
    if xmin > 25 or ymin > 25 or xmax < 975 or ymax < 975:
        return False

    words = lambda value: {
        word for word in re.findall(r"[a-z0-9]+", (value or "").lower())
        if len(word) > 2
    }
    description_words = words(description)
    background_words = words(background)
    if not description_words or not background_words:
        return False
    overlap = len(description_words & background_words)
    return overlap / min(len(description_words), len(background_words)) >= 0.75


def _scene_background(value):
    background = (value or "").strip()
    if background.lower() == "transparent background":
        return background
    if len(background.split()) <= 6:
        background = (
            f"A fully rendered interior or environmental scene of {background}, "
            "with visible surrounding architecture or scenery, ground or floor, "
            "natural depth, and ambient lighting."
        )
    return (
        f"{background} The environment fills the entire frame as a fully rendered "
        "opaque background behind all foreground elements."
    )


def build_structured_caption(
    high_level,
    background,
    style_kind,
    aesthetics,
    lighting,
    medium,
    style_detail,
    palette,
    layout_json,
):
    caption = OrderedDict()
    if (high_level or "").strip():
        caption["high_level_description"] = high_level.strip()

    style = OrderedDict()
    if style_kind == "Photograph":
        style["aesthetics"] = (
            (aesthetics or "").strip()
            or "realistic, natural, highly detailed photography"
        )
        style["lighting"] = (
            (lighting or "").strip()
            or "naturalistic lighting with realistic shadows and highlights"
        )
        style["photo"] = (
            (style_detail or "").strip()
            or "realistic photographic composition with natural perspective"
        )
        style["medium"] = (medium or "").strip() or "photograph"
    else:
        style["aesthetics"] = (
            (aesthetics or "").strip()
            or "polished, cohesive, highly detailed artwork"
        )
        style["lighting"] = (
            (lighting or "").strip()
            or "clear illustrative lighting with consistent shadows"
        )
        style["medium"] = (medium or "").strip() or "digital illustration"
        style["art_style"] = (
            (style_detail or "").strip()
            or "detailed digital artwork with a consistent visual style"
        )
    colors = _palette(palette, 16)
    if colors:
        style["color_palette"] = colors
    caption["style_description"] = style

    try:
        regions = json.loads(layout_json or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid visual-layout data: {exc}") from exc

    elements = []
    for region in regions:
        if not isinstance(region, dict):
            continue
        element = OrderedDict()
        element_type = "text" if region.get("type") == "text" else "obj"
        element["type"] = element_type
        bbox = region.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            try:
                x = float(region["x"])
                y = float(region["y"])
                width = float(region["w"])
                height = float(region["h"])
                scale = 1000 if max(abs(x), abs(y), abs(width), abs(height)) <= 1 else 10
                bbox = [
                    y * scale,
                    x * scale,
                    (y + height) * scale,
                    (x + width) * scale,
                ]
            except (KeyError, TypeError, ValueError):
                bbox = None
        if isinstance(bbox, list) and len(bbox) == 4:
            bbox = [
                max(0, min(1000, int(round(float(value))))) for value in bbox
            ]
            element["bbox"] = bbox
        description = str(region.get("desc") or "").strip()
        if (
            element_type == "obj"
            and _duplicates_background(description, background, bbox)
        ):
            continue
        if element_type == "text":
            element["text"] = str(region.get("text") or "").strip()
        element["desc"] = description
        colors = _palette(region.get("palette"), 5)
        if colors:
            element["color_palette"] = colors
        box_color = _palette(
            [region.get("color") or region.get("box_color")],
            1,
        )
        if box_color:
            element["box_color"] = box_color[0]
        elements.append(element)

    caption["compositional_deconstruction"] = OrderedDict([
        ("background", _scene_background(background)),
        ("elements", elements),
    ])
    return json.dumps(caption, ensure_ascii=False, separators=(",", ":"))


def _save_last_settings(values):
    keys = (
        "prompt", "repo", "preset", "width", "height", "seed",
        "allow_warnings", "use_builder", "high_level", "background",
        "style_kind", "aesthetics", "lighting", "medium", "style_detail",
        "palette", "layout_json",
    )
    data = dict(zip(keys, values))
    temporary = LAST_SETTINGS_PATH.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(LAST_SETTINGS_PATH)


def restore_last_settings():
    defaults = (
        "", "ideogram-ai/ideogram-4-nf4", "V4_DEFAULT_20", 1024, 1024, -1,
        True, False, "", "", "Photograph", "", "", "photograph", "", "",
        "",
    )
    try:
        data = json.loads(LAST_SETTINGS_PATH.read_text(encoding="utf-8"))
        keys = (
            "prompt", "repo", "preset", "width", "height", "seed",
            "allow_warnings", "use_builder", "high_level", "background",
            "style_kind", "aesthetics", "lighting", "medium", "style_detail",
            "palette", "layout_json",
        )
        return tuple(data.get(key, default) for key, default in zip(keys, defaults))
    except (OSError, ValueError, TypeError):
        return defaults


def clear_prompt_settings():
    return (
        "", "ideogram-ai/ideogram-4-nf4", "V4_DEFAULT_20", 1024, 1024, -1,
        True, False, "", "", "Photograph", "", "", "photograph", "", "",
        "",
    )


def _prompt_seed(prompt, fallback):
    try:
        parsed = json.loads((prompt or "").strip())
    except (json.JSONDecodeError, TypeError):
        return prompt, int(fallback)

    caption = parsed
    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
        caption = parsed[0]
    if not isinstance(caption, dict):
        return prompt, -1

    seed = caption.pop("seed", None)
    if seed is None:
        settings = caption.get("settings")
        if isinstance(settings, dict):
            seed = settings.get("seed")
    try:
        selected_seed = int(seed) if seed is not None else -1
    except (TypeError, ValueError):
        selected_seed = -1

    if isinstance(parsed, list):
        cleaned = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    else:
        cleaned = json.dumps(caption, ensure_ascii=False, separators=(",", ":"))
    return cleaned, selected_seed


def read_ideogram_png(image):
    if image is None:
        return "Upload an Ideogram PNG to inspect its metadata.", "", ""

    info = image.info or {}
    caption_text = info.get("ideogram4_caption", "")
    settings_text = info.get("ideogram4_settings", "")
    if not caption_text and not settings_text:
        return "No Ideogram 4 metadata was found in this image.", "", ""

    try:
        caption = json.loads(caption_text) if caption_text else {}
        settings = json.loads(settings_text) if settings_text else {}
    except (json.JSONDecodeError, TypeError) as exc:
        return f"Embedded Ideogram metadata is invalid: `{exc}`", "", ""

    payload = {"caption": caption, "settings": settings}
    summary = (
        f"**Model:** `{settings.get('model', 'unknown')}`  \n"
        f"**Preset:** `{settings.get('preset', 'unknown')}`  \n"
        f"**Steps:** `{settings.get('steps', 'unknown')}`  \n"
        f"**Seed:** `{settings.get('seed', 'unknown')}`  \n"
        f"**Size:** `{settings.get('width', image.width)}x"
        f"{settings.get('height', image.height)}`"
    )
    return (
        summary,
        json.dumps(payload, ensure_ascii=False, indent=2),
        json.dumps(payload, ensure_ascii=False),
    )


def send_png_to_builder(payload_text):
    try:
        payload = json.loads(payload_text or "{}")
        caption = payload.get("caption") or {}
        settings = payload.get("settings") or {}
        style = caption.get("style_description") or {}
        composition = caption.get("compositional_deconstruction") or {}

        regions = []
        for element in composition.get("elements") or []:
            bbox = element.get("bbox")
            if not (isinstance(bbox, list) and len(bbox) == 4):
                continue
            ymin, xmin, ymax, xmax = [float(value) for value in bbox]
            regions.append({
                "x": xmin / 1000,
                "y": ymin / 1000,
                "w": (xmax - xmin) / 1000,
                "h": (ymax - ymin) / 1000,
                "type": "text" if element.get("type") == "text" else "obj",
                "text": str(element.get("text") or ""),
                "desc": str(element.get("desc") or ""),
                "palette": element.get("color_palette") or [],
                "color": str(
                    element.get("box_color")
                    or element.get("color")
                    or "#9E9E9E"
                ),
            })

        style_kind = "Photograph" if "photo" in style else "Artwork"
        style_detail = style.get("photo", "") if style_kind == "Photograph" else style.get("art_style", "")
        return (
            str(caption.get("high_level_description") or ""),
            str(composition.get("background") or ""),
            style_kind,
            str(style.get("aesthetics") or ""),
            str(style.get("lighting") or ""),
            str(style.get("medium") or ""),
            str(style_detail or ""),
            " ".join(style.get("color_palette") or []),
            json.dumps(regions, ensure_ascii=False, separators=(",", ":")),
            str(settings.get("model") or "ideogram-ai/ideogram-4-nf4"),
            str(settings.get("preset") or "V4_DEFAULT_20"),
            int(settings.get("width") or 1024),
            int(settings.get("height") or 1024),
            int(settings.get("seed", -1)),
            True,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise gr.Error(f"Could not load Ideogram PNG metadata: {exc}") from exc


def generate(
    prompt,
    repo,
    hf_token,
    preset,
    width,
    height,
    seed,
    magic_prompt_key,
    allow_warnings,
    use_builder,
    high_level,
    background,
    style_kind,
    aesthetics,
    lighting,
    medium,
    style_detail,
    palette,
    layout_json,
    progress=gr.Progress(),
):
    try:
        _save_last_settings((
            prompt, repo, preset, width, height, seed, allow_warnings,
            use_builder, high_level, background, style_kind, aesthetics,
            lighting, medium, style_detail, palette, layout_json,
        ))
        if use_builder:
            prompt = build_structured_caption(
                high_level,
                background,
                style_kind,
                aesthetics,
                lighting,
                medium,
                style_detail,
                palette,
                layout_json,
            )
            magic_prompt_key = ""
            selected_seed = int(seed)
        else:
            prompt, selected_seed = _prompt_seed(prompt, seed)

        payload = {
            "action": "generate",
            "prompt": prompt,
            "repo": repo,
            "hf_token": hf_token,
            "preset": preset,
            "width": int(width),
            "height": int(height),
            "seed": selected_seed,
            "magic_prompt_key": magic_prompt_key,
            "allow_caption_warnings": allow_warnings,
            "output_dir": str(OUTPUT_DIR),
        }
        with _LOCK:
            _start_worker()
            with Client(ADDRESS, authkey=AUTHKEY) as connection:
                connection.send(payload)
                while True:
                    message = connection.recv()
                    if message.get("event") == "log":
                        continue
                    if message.get("event") == "progress":
                        current = int(message.get("current") or 0)
                        total = max(1, int(message.get("total") or 1))
                        stage = str(message.get("stage") or "working")
                        if total > 1:
                            line = (
                                f"{stage}: {current}/{total} "
                                f"({current / total:.0%})"
                            )
                            progress((current, total), desc=line)
                        else:
                            line = f"{stage}: {'complete' if current else 'working...'}"
                            progress(current, desc=line)
                        continue
                    response = (
                        message["response"]
                        if message.get("event") == "result"
                        else message
                    )
                    break
        if not response.get("ok"):
            raise RuntimeError(
                response.get("error", "Ideogram worker failed")
                + "\n\n"
                + response.get("traceback", "")
            )
        return response["image"], response["caption"]
    except Exception as exc:
        raise gr.Error(f"Generation failed: {exc}") from exc


def on_ui_tabs():
    with gr.Blocks(analytics_enabled=False, elem_id="i4-page") as tab:
        gr.Markdown(
            "## Ideogram 4 NF4\n"
            "Runs Ideogram's official inference package in an isolated environment. "
            "The first load downloads the gated model from Hugging Face. Unload "
            "Forge's regular checkpoint first if VRAM is tight."
        )
        gr.HTML(
            """
            <div class="i4-page-toolbar">
              <button type="button" id="i4-capture-page">
                Download full-page screenshot
              </button>
              <span>Captures the complete Forge page at its current layout.</span>
            </div>
            """
        )
        with gr.Row(elem_id="i4-main-split"):
            with gr.Column(elem_id="i4-left-pane"):
                with gr.Tabs():
                    with gr.Tab("Prompt"):
                        prompt = gr.Textbox(
                            label="Plain prompt or hand-written JSON caption",
                            lines=12,
                            placeholder="A poster for...",
                        )
                    with gr.Tab("Visual JSON Builder", elem_id="i4-visual-tab"):
                        use_builder = gr.Checkbox(
                            value=False,
                            label="Use visual builder for generation",
                            elem_id="i4-use-builder",
                        )
                        high_level = gr.Textbox(
                            label="High-level description",
                            lines=2,
                            elem_id="i4-high-level",
                        )
                        background = gr.Textbox(
                            label="Background / environment",
                            lines=3,
                            elem_id="i4-background",
                        )
                        with gr.Accordion("Style", open=False):
                            style_kind = gr.Radio(
                                ["Photograph", "Artwork"],
                                value="Photograph",
                                label="Style type",
                                elem_id="i4-style-kind",
                            )
                            aesthetics = gr.Textbox(
                                label="Aesthetics",
                                elem_id="i4-aesthetics",
                                lines=4,
                                max_lines=4,
                            )
                            lighting = gr.Textbox(
                                label="Lighting",
                                elem_id="i4-lighting",
                                lines=4,
                                max_lines=4,
                            )
                            medium = gr.Textbox(
                                label="Medium",
                                value="photograph",
                                elem_id="i4-medium",
                                lines=4,
                                max_lines=4,
                            )
                            style_detail = gr.Textbox(
                                label="Camera details or art style",
                                elem_id="i4-style-detail",
                                lines=4,
                                max_lines=4,
                            )
                            palette = gr.Textbox(
                                label="Overall palette",
                                placeholder="#1B1B2F #E43F5A #F5F5F5",
                                elem_id="i4-overall-palette",
                                lines=4,
                                max_lines=4,
                            )
                        gr.HTML(
                            """
                            <div id="i4-builder">
                              <div class="i4-builder-toolbar">
                                <button type="button" id="i4-add-object">Add object</button>
                                <button type="button" id="i4-add-text">Add text</button>
                                <button type="button" id="i4-delete-region">Delete selected</button>
                                <button type="button" id="i4-toggle-canvas-preview">Show last image</button>
                              </div>
                              <div class="i4-builder-note">
                                Keep walls, floors, windows, lighting, and the general room
                                only in Background. Add boxes for subjects, furniture,
                                decor, and literal text.
                              </div>
                              <div class="i4-builder-layout">
                                <div id="i4-canvas-wrap"><div id="i4-canvas"></div></div>
                                <div class="i4-region-editor">
                                  <label>Selected box
                                    <select id="i4-region-select"></select>
                                  </label>
                                  <label>Box color
                                    <input id="i4-region-color" type="color" value="#9E9E9E">
                                  </label>
                                  <label>Selected type
                                    <select id="i4-region-type"><option value="obj">Object</option><option value="text">Text</option></select>
                                  </label>
                                  <label id="i4-literal-label">Literal text
                                    <textarea id="i4-region-text" rows="2" placeholder="Text shown in the image"></textarea>
                                  </label>
                                  <label>Description
                                    <textarea id="i4-region-desc" rows="9" placeholder="Describe this object or text region"></textarea>
                                  </label>
                                  <label>Element palette
                                    <input id="i4-region-palette" placeholder="#FF0000 #FFFFFF">
                                  </label>
                                  <fieldset id="i4-region-bbox">
                                    <legend>Bounding box [y1, x1, y2, x2]</legend>
                                    <input id="i4-bbox-y1" type="number" min="0" max="1000" step="1" aria-label="Top">
                                    <input id="i4-bbox-x1" type="number" min="0" max="1000" step="1" aria-label="Left">
                                    <input id="i4-bbox-y2" type="number" min="0" max="1000" step="1" aria-label="Bottom">
                                    <input id="i4-bbox-x2" type="number" min="0" max="1000" step="1" aria-label="Right">
                                  </fieldset>
                                </div>
                              </div>
                            </div>
                            """
                        )
                        layout_json = gr.Textbox(
                            value="",
                            label="Generated element layout JSON",
                            elem_id="i4-layout-json",
                            lines=5,
                            interactive=True,
                            placeholder='[{"x":0.1,"y":0.1,"w":0.4,"h":0.4,"type":"obj","text":"","desc":"...","palette":[]}]',
                        )
                        gr.HTML(
                            '<button type="button" id="i4-import-layout">'
                            'Import JSON into Visual Builder</button>'
                        )
                    with gr.Tab("PNG Info", elem_id="i4-png-info-tab"):
                        with gr.Row(elem_id="i4-png-info-layout"):
                            with gr.Column(elem_id="i4-png-preview-column"):
                                png_source = gr.Image(
                                    label="Source",
                                    source="upload",
                                    interactive=True,
                                    type="pil",
                                    image_mode="RGBA",
                                    elem_id="i4-png-source",
                                )
                            with gr.Column(elem_id="i4-png-json-column"):
                                png_metadata = gr.Textbox(
                                    label="JSON prompt",
                                    lines=18,
                                    max_lines=18,
                                    interactive=False,
                                )
                                png_to_builder = gr.Button(
                                    "Send to Visual JSON Builder",
                                    variant="primary",
                                    elem_id="i4-send-png-builder",
                                )
                        png_summary = gr.Markdown(visible=False)
                        png_payload = gr.Textbox(visible=False)
                with gr.Column(elem_id="i4-generation-controls"):
                    repo = gr.Textbox(
                        label="Hugging Face model repository",
                        value="ideogram-ai/ideogram-4-nf4",
                    )
                    hf_token = gr.Textbox(
                        label="Hugging Face token",
                        type="password",
                        placeholder="Required unless already logged in; kept in memory only",
                    )
                    with gr.Row():
                        preset = gr.Dropdown(
                            ["V4_TURBO_12", "V4_DEFAULT_20", "V4_QUALITY_48"],
                            value="V4_DEFAULT_20",
                            label="Sampler preset",
                        )
                        seed = gr.Number(
                            value=-1,
                            precision=0,
                            label="Seed (-1 = random)",
                            elem_id="i4-seed",
                        )
                    with gr.Row():
                        width = gr.Slider(
                            256, 2048, value=1024, step=16, label="Width",
                            elem_id="i4-width",
                        )
                        height = gr.Slider(
                            256, 2048, value=1024, step=16, label="Height",
                            elem_id="i4-height",
                        )
                    magic_prompt_key = gr.Textbox(
                        label="Ideogram API key for Magic Prompt (optional)",
                        type="password",
                        placeholder="Leave blank for direct/plain or JSON prompting",
                    )
                    allow_warnings = gr.Checkbox(
                        value=True,
                        label="Allow caption verifier warnings",
                        info="Useful for plain-text prompts. Disable for strict JSON validation.",
                    )
                    gr.HTML(
                        '<div class="i4-first-generation-note">'
                        'The first generation will take longer as the model loads '
                        'into memory. Please allow several minutes.'
                        '</div>'
                    )
                    with gr.Row():
                        generate_button = gr.Button("Generate", variant="primary")
                        restore_button = gr.Button(
                            "↙️",
                            tooltip="Restore settings from the last generation attempt",
                            elem_id="i4-load-previous",
                        )
                        clear_button = gr.Button(
                            "🗑️",
                            tooltip="Clear the prompt and restore builder defaults",
                            elem_id="i4-clear-prompt",
                        )
            gr.HTML(
                '<div id="i4-main-divider" role="separator" '
                'aria-orientation="vertical" title="Drag to resize panels"></div>',
                elem_id="i4-divider-slot",
            )
            with gr.Column(elem_id="i4-right-pane"):
                gr.HTML(
                    """
                    <div class="i4-output-toolbar">
                      <button type="button" id="i4-toggle-output-overlay"
                              aria-pressed="false">
                        Show layout overlay
                      </button>
                      <span>Display only; downloaded and opened images stay unchanged.</span>
                    </div>
                    """
                )
                image = gr.Image(
                    label="Output",
                    type="filepath",
                    elem_id="i4-output-image",
                )
                expanded_caption = gr.Textbox(
                    label="Caption used for generation",
                    lines=10,
                    interactive=False,
                    elem_id="i4-expanded-caption",
                )

        generate_button.click(
            generate,
            [
                prompt,
                repo,
                hf_token,
                preset,
                width,
                height,
                seed,
                magic_prompt_key,
                allow_warnings,
                use_builder,
                high_level,
                background,
                style_kind,
                aesthetics,
                lighting,
                medium,
                style_detail,
                palette,
                layout_json,
            ],
            [image, expanded_caption],
        )
        saved_components = [
            prompt, repo, preset, width, height, seed, allow_warnings,
            use_builder, high_level, background, style_kind, aesthetics,
            lighting, medium, style_detail, palette, layout_json,
        ]
        restore_button.click(
            restore_last_settings,
            None,
            saved_components,
            show_progress=False,
        )
        clear_button.click(
            clear_prompt_settings,
            None,
            saved_components,
            show_progress=False,
        )
        png_source.change(
            read_ideogram_png,
            png_source,
            [png_summary, png_metadata, png_payload],
            show_progress=False,
        )
        png_to_builder.click(
            send_png_to_builder,
            png_payload,
            [
                high_level,
                background,
                style_kind,
                aesthetics,
                lighting,
                medium,
                style_detail,
                palette,
                layout_json,
                repo,
                preset,
                width,
                height,
                seed,
                use_builder,
            ],
            show_progress=False,
        )

    return [(tab, "Ideogram 4", "ideogram4_forge")]


script_callbacks.on_ui_tabs(on_ui_tabs)
