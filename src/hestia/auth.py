"""Passkey authentication for the single Hestia owner.

Opt-in: when ``HESTIA_SETUP_TOKEN`` is unset the app stays open, as before. When
set, every ``/api/*`` call except ``/api/auth/*`` needs a signed session
cookie. The setup token bootstraps the first passkey and doubles as the
recovery path if a device is lost.

WebAuthn ceremonies are held in memory for a few minutes (single user, short
lived); sessions are stateless HMAC-signed cookies, keyed by a random secret
persisted in the data directory.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time

from fido2 import cbor
from fido2.cose import CoseKey
from fido2.server import Fido2Server
from fido2.utils import websafe_decode, websafe_encode
from fido2.webauthn import (
    AttestedCredentialData,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialUserEntity,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)
from sqlmodel import Session, select

from hestia import config
from hestia.registry.models import Passkey

SESSION_COOKIE = "hestia_session"
SESSION_TTL = 30 * 24 * 3600  # 30 days
CEREMONY_TTL = 300  # 5 minutes

_OWNER = PublicKeyCredentialUserEntity(id=b"owner", name="owner", display_name="Hestia owner")
_ceremonies: dict[str, tuple[float, object]] = {}


def enabled() -> bool:
    return bool(os.environ.get("HESTIA_SETUP_TOKEN"))


def check_setup_token(token: str | None) -> bool:
    expected = os.environ.get("HESTIA_SETUP_TOKEN") or ""
    return bool(expected) and hmac.compare_digest(expected, token or "")


def cookie_secure(scheme: str) -> bool:
    return scheme == "https" or os.environ.get("HESTIA_COOKIE_SECURE") == "1"


# --------------------------------------------------------------------------
# sessions (stateless signed cookie)
# --------------------------------------------------------------------------

def _secret() -> bytes:
    path = config.data_dir() / "auth_secret"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(secrets.token_bytes(32))
    return path.read_bytes()


def make_session() -> str:
    expires = str(int(time.time()) + SESSION_TTL)
    sig = hmac.new(_secret(), expires.encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def verify_session(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    payload, _, sig = token.partition(".")
    expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False
    try:
        return int(payload) > time.time()
    except ValueError:
        return False


# --------------------------------------------------------------------------
# WebAuthn ceremonies
# --------------------------------------------------------------------------

def _server(request) -> Fido2Server:
    rp_id = os.environ.get("HESTIA_RP_ID") or request.url.hostname or "localhost"
    origin = os.environ.get("HESTIA_ORIGIN") or f"{request.url.scheme}://{request.url.netloc}"
    return Fido2Server(
        PublicKeyCredentialRpEntity(id=rp_id, name="Hestia"),
        verify_origin=lambda candidate: candidate == origin,
    )


def _stash(state) -> str:
    now = time.time()
    for key in [k for k, (expires, _) in _ceremonies.items() if expires < now]:
        _ceremonies.pop(key, None)
    token = secrets.token_urlsafe(16)
    _ceremonies[token] = (now + CEREMONY_TTL, state)
    return token


def _pop(ceremony: str | None):
    entry = _ceremonies.pop(ceremony or "", None)
    if not entry or entry[0] < time.time():
        return None
    return entry[1]


def _credentials(db: Session) -> list[AttestedCredentialData]:
    out = []
    for row in db.exec(select(Passkey)).all():
        out.append(
            AttestedCredentialData.create(
                base64.b64decode(row.aaguid or ""),
                websafe_decode(row.credential_id),
                CoseKey.parse(cbor.decode(base64.b64decode(row.public_key))),
            )
        )
    return out


def has_passkeys(db: Session) -> bool:
    return db.exec(select(Passkey)).first() is not None


def register_begin(db: Session, request) -> dict:
    options, state = _server(request).register_begin(
        _OWNER,
        credentials=_credentials(db),
        resident_key_requirement=ResidentKeyRequirement.PREFERRED,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return {"ceremony": _stash(state), "options": dict(options)}


def register_complete(db: Session, request, ceremony: str | None, credential: dict) -> Passkey:
    state = _pop(ceremony)
    if state is None:
        raise ValueError("registration ceremony expired, try again")
    auth_data = _server(request).register_complete(state, credential)
    data = auth_data.credential_data
    row = Passkey(
        credential_id=websafe_encode(data.credential_id),
        public_key=base64.b64encode(cbor.encode(dict(data.public_key))).decode(),
        aaguid=base64.b64encode(data.aaguid).decode(),
        sign_count=auth_data.counter,
        transports=",".join((credential.get("response") or {}).get("transports") or []),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def login_begin(db: Session, request) -> dict:
    credentials = _credentials(db)
    if not credentials:
        raise ValueError("no passkeys registered yet")
    options, state = _server(request).authenticate_begin(
        credentials, user_verification=UserVerificationRequirement.PREFERRED
    )
    return {"ceremony": _stash(state), "options": dict(options)}


def login_complete(db: Session, request, ceremony: str | None, credential: dict) -> None:
    state = _pop(ceremony)
    if state is None:
        raise ValueError("login ceremony expired, try again")
    _server(request).authenticate_complete(state, _credentials(db), credential)
