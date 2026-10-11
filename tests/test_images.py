"""Image generation tool: fake image API writing into the workspace."""

import base64
import json
from types import SimpleNamespace

from hestia.tools import images
from hestia.tools.registry import ProjectContext


class FakeResponse:
    def __init__(self, payload, status_code=200, content=b""):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)[:300]
        self.content = content

    def json(self):
        return self._payload


class FakeHTTPClient:
    calls: list = []
    response: FakeResponse | None = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, headers=None, json=None):
        FakeHTTPClient.calls.append((url, headers, json))
        return FakeHTTPClient.response

    def get(self, url, timeout=None):
        return FakeHTTPClient.response


def test_generate_image_writes_workspace_file(tmp_path, monkeypatch):
    png = b"\x89PNG\r\n\x1a\nfakepng"
    FakeHTTPClient.calls = []
    FakeHTTPClient.response = FakeResponse(
        {"data": [{"b64_json": base64.b64encode(png).decode()}]}
    )
    monkeypatch.setattr(images.httpx, "Client", FakeHTTPClient)

    provider = SimpleNamespace(
        base_url="http://img",
        api_key="k",
        api_key_env="",
        model="chat-model",
        models='["gpt-image-1", "chat-model"]',
    )
    ctx = ProjectContext(
        project_id=7,
        name="t",
        repo_url="",
        local_path=tmp_path,
        workspace_path=tmp_path / "ws",
    )

    result = images.make_tools(provider)[0].handler(ctx, {"prompt": "a red fox in snow"})

    url, headers, payload = FakeHTTPClient.calls[0]
    assert url == "http://img/v1/images/generations"
    assert headers["Authorization"] == "Bearer k"
    assert payload["model"] == "gpt-image-1"  # image-capable model picked from the list
    assert result["path"].startswith("images/")
    assert (ctx.workspace_path / result["path"]).read_bytes() == png
    assert result["markdown"] == f"![a red fox in snow]({result['url']})"
    assert result["url"] == f"/api/projects/7/workspace/raw?path={result['path']}"


def test_generate_image_url_fallback(tmp_path, monkeypatch):
    FakeHTTPClient.calls = []
    FakeHTTPClient.response = FakeResponse({"data": [{"url": "http://cdn/x.jpg"}]}, content=b"jpegbytes")
    monkeypatch.setattr(images.httpx, "Client", FakeHTTPClient)

    provider = SimpleNamespace(base_url="http://img", api_key=None, api_key_env="", model="m", models="[]")
    ctx = ProjectContext(
        project_id=1,
        name="t",
        repo_url="",
        local_path=tmp_path,
        workspace_path=tmp_path / "ws",
    )

    result = images.make_tools(provider)[0].handler(ctx, {"prompt": "cat", "filename": "cat"})
    assert result["path"].endswith(".png")  # unknown bytes default to png
