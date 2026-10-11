"""Passkey auth gate and sessions."""




def test_auth_disabled_by_default(client):
    data = client.get("/api/auth/status").json()
    assert data["enabled"] is False
    assert data["authenticated"] is True
    assert client.get("/api/projects").status_code == 200


def test_auth_gate_and_session(client, monkeypatch):
    from hestia import auth

    monkeypatch.setenv("HESTIA_SETUP_TOKEN", "s3cret")

    assert client.get("/api/projects").status_code == 401
    data = client.get("/api/auth/status").json()
    assert data == {
        "enabled": True,
        "authenticated": False,
        "has_passkeys": False,
        "rp_id": "testserver",
    }

    assert client.post(
        "/api/auth/register/begin", json={"setup_token": "nope"}
    ).status_code == 403
    begin = client.post(
        "/api/auth/register/begin", json={"setup_token": "s3cret"}
    ).json()
    assert begin["options"]["publicKey"]["challenge"]
    assert begin["ceremony"]

    assert client.post("/api/auth/login/begin", json={}).status_code == 400

    client.cookies.set(auth.SESSION_COOKIE, auth.make_session())
    assert client.get("/api/projects").status_code == 200
    assert client.get("/api/auth/status").json()["authenticated"] is True

    client.cookies.set(auth.SESSION_COOKIE, "9999999999.deadbeef")
    assert client.get("/api/projects").status_code == 401
