"""Skill installation, parsing, and safe extraction."""

import pytest


def test_skills_install_list_read_remove(client, tmp_path):
    src = tmp_path / "my-skill"
    src.mkdir()
    (src / "SKILL.md").write_text(
        "---\nname: PDF Tools\ndescription: Extract text from PDFs.\n---\n"
        "# PDF Tools\nUse pdftotext to extract.\n"
    )

    resp = client.post("/api/skills/install", json={"source": str(src)})
    assert resp.status_code == 201, resp.text
    installed = resp.json()
    assert installed[0]["name"] == "PDF Tools"
    assert installed[0]["description"] == "Extract text from PDFs."
    slug = installed[0]["slug"]

    assert [s["slug"] for s in client.get("/api/skills").json()] == [slug]
    detail = client.get(f"/api/skills/{slug}").json()
    assert "pdftotext" in detail["body"]

    assert client.delete(f"/api/skills/{slug}").status_code == 204
    assert client.get("/api/skills").json() == []


def test_skills_install_collection(client, tmp_path):
    root = tmp_path / "collection"
    for name in ("alpha", "beta"):
        d = root / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"# {name}\nDoes {name} things.\n")

    resp = client.post("/api/skills/install", json={"source": str(root), "subpath": "skills"})
    assert resp.status_code == 201, resp.text
    assert sorted(s["name"] for s in resp.json()) == ["alpha", "beta"]
    assert sorted(s["slug"] for s in client.get("/api/skills").json()) == ["alpha", "beta"]


def test_skills_invalid_source(client):
    assert client.post("/api/skills/install", json={"source": "definitely not a source"}).status_code == 400
    assert client.post("/api/skills/install", json={"source": ""}).status_code == 400


def test_skill_source_parsing():
    from hestia import skills

    assert skills.parse_source("owner/repo") == ("git", "https://github.com/owner/repo", None)
    assert skills.parse_source("owner/repo#skills/pdf") == (
        "git",
        "https://github.com/owner/repo",
        "skills/pdf",
    )
    assert skills.parse_source("npm:left-pad") == ("npm", "left-pad", None)
    assert skills.parse_source("https://example.com/x.tar.gz")[0] == "archive"
    assert skills.parse_source("https://github.com/o/r")[0] == "git"
    with pytest.raises(skills.InvalidSource):
        skills.parse_source("not a source")


def test_skill_safe_extract_rejects_traversal(tmp_path):
    import io
    import zipfile

    from hestia import skills

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("../evil.txt", "x")
    with pytest.raises(skills.InvalidSource):
        skills._safe_extract(buf.getvalue(), tmp_path / "out")


def test_skill_extract_tarball(tmp_path):
    import io
    import tarfile

    from hestia import skills

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        data = b"# hello\n"
        info = tarfile.TarInfo("SKILL.md")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    skills._safe_extract(buf.getvalue(), tmp_path / "out")
    assert (tmp_path / "out" / "SKILL.md").read_text() == "# hello\n"
