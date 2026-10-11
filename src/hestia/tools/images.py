"""Image generation tool: OpenAI-compatible /v1/images/generations.

Registered with a provider, because image generation uses its own model
(gpt-image-1, flux, ...) separate from the chat model. A model listed by the
provider whose name looks image-capable wins; an explicit ``model`` argument
overrides everything. The result is written into the project workspace so it
shows up in the gallery.
"""

import base64
import json
import re
import time
from urllib.parse import quote

import httpx

from hestia.providers.base import resolve_api_key
from hestia.tools.registry import ProjectContext, Tool, schema

_IMAGE_HINTS = (
    "gpt-image",
    "dall-e",
    "dalle",
    "image-gen",
    "imagegen",
    "flux",
    "stable-diffusion",
    "sdxl",
    "imagen",
    "recraft",
    "seedream",
    "ideogram",
    "photon",
    "-image",
)


def make_tools(provider) -> list[Tool]:
    return [
        Tool(
            name="generate_image",
            description=(
                "Generate an image from a text prompt and save it in the project "
                "workspace. Write a vivid, detailed prompt. Always include the "
                "returned markdown link in your reply so the owner sees the image."
            ),
            parameters=schema(
                {
                    "prompt": {"type": "string", "description": "what to draw"},
                    "size": {
                        "type": "string",
                        "description": "optional size, e.g. 1024x1024",
                    },
                    "filename": {
                        "type": "string",
                        "description": "optional file name (default: slug of the prompt)",
                    },
                    "model": {
                        "type": "string",
                        "description": "optional image model override",
                    },
                },
                ["prompt"],
            ),
            handler=lambda ctx, args: _generate(ctx, provider, args),
            group="images",
            effect="write",
        )
    ]


def _pick_model(provider, override: str | None) -> str:
    if override:
        return override
    try:
        models = json.loads(provider.models or "[]")
    except ValueError:
        models = []
    for model in models:
        low = model.lower()
        if any(hint in low for hint in _IMAGE_HINTS):
            return model
    return provider.model


def _ext(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8"):
        return "jpg"
    if raw.startswith(b"GIF8"):
        return "gif"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "webp"
    return "png"


def _generate(ctx: ProjectContext, provider, args: dict) -> dict:
    prompt = (args.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    if ctx.workspace_path is None:
        raise ValueError("project has no workspace")
    model = _pick_model(provider, args.get("model"))
    payload: dict = {"model": model, "prompt": prompt, "n": 1}
    if args.get("size"):
        payload["size"] = args["size"]
    headers = {"Content-Type": "application/json"}
    key = resolve_api_key(provider)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    with httpx.Client(timeout=300.0) as client:
        resp = client.post(
            f"{provider.base_url.rstrip('/')}/v1/images/generations",
            headers=headers,
            json=payload,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"image API {resp.status_code}: {resp.text[:300]}")
        data = (resp.json().get("data") or [{}])[0]
        if data.get("b64_json"):
            raw = base64.b64decode(data["b64_json"])
        elif data.get("url"):
            raw = client.get(data["url"], timeout=300.0).content
        else:
            raise RuntimeError("image API returned no image")

    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:48].strip("-")
    name = args.get("filename") or f"{slug or 'image'}-{int(time.time())}"
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "image"
    if not name.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        name = f"{name}.{_ext(raw)}"

    root = ctx.workspace_path.resolve()
    path = (root / "images" / name).resolve()
    if not str(path).startswith(str(root) + "/"):
        raise PermissionError("path escapes workspace")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    rel = str(path.relative_to(root))
    url = f"/api/projects/{ctx.project_id}/workspace/raw?path={quote(rel)}"
    return {
        "path": rel,
        "url": url,
        "bytes": len(raw),
        "model": model,
        "markdown": f"![{prompt[:60]}]({url})",
    }
