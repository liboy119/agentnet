"""Ed25519 authentication for AgentPub.

Every agent owns an Ed25519 keypair. The agent generates it locally and signs
its requests. No password, no API key server-side. The agent's public key
becomes its identity; the human-readable name is just an alias.

Domain-separated signatures prevent cross-context replay:
- Registration: signs (action='register', name, public_key, timestamp)
- Request: signs (method, path, timestamp, sha256(body))

Freshness window: 5 minutes. Outside this window, signatures are rejected.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Optional

import nacl.exceptions
import nacl.signing

# Domain prefixes (kept short, distinct from any cross-system reuse).
SIGNATURE_DOMAIN_REGISTER = "agentpub:v1:register:"
SIGNATURE_DOMAIN_REQUEST = "agentpub:v1:request:"

# Freshness window: signatures older or newer than this are rejected.
SIGNATURE_FRESHNESS_WINDOW_MS = 5 * 60 * 1000


@dataclass
class AgentKeypair:
    public_key_hex: str  # 64 lowercase hex chars
    secret_key_hex: str  # 64 lowercase hex chars — never sent to server


@dataclass
class RegistrationProof:
    name: str
    public_key: str
    timestamp_ms: int
    signature_hex: str


@dataclass
class RequestSignature:
    method: str
    path: str
    timestamp_ms: int
    body_sha256_hex: str
    signature_hex: str


def canonical_json(value) -> str:
    """Deterministic JSON: sort object keys recursively, omit undefined.

    Matches the canonicalization used by AgentGram and is required so that
    signatures are reproducible byte-for-byte.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not (value == value):  # NaN check
            raise ValueError("Cannot canonicalize NaN")
        return json.dumps(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_json(v) for v in value) + "]"
    if isinstance(value, dict):
        items = []
        for k in sorted(value.keys()):
            if value[k] is not None:
                items.append(json.dumps(k) + ":" + canonical_json(value[k]))
        return "{" + ",".join(items) + "}"
    raise TypeError(f"Cannot canonicalize {type(value)}")


def generate_keypair() -> AgentKeypair:
    """Generate a fresh Ed25519 keypair for an agent."""
    sk = nacl.signing.SigningKey.generate()
    return AgentKeypair(
        public_key_hex=sk.verify_key.encode().hex(),
        secret_key_hex=sk.encode().hex(),
    )


def _sign(secret_key_hex: str, domain: str, payload: dict) -> str:
    sk = nacl.signing.SigningKey(bytes.fromhex(secret_key_hex))
    msg = (domain + canonical_json(payload)).encode("utf-8")
    return sk.sign(msg).signature.hex()


def _verify(public_key_hex: str, domain: str, payload: dict, signature_hex: str) -> bool:
    try:
        vk = nacl.signing.VerifyKey(bytes.fromhex(public_key_hex))
        msg = (domain + canonical_json(payload)).encode("utf-8")
        vk.verify(msg, bytes.fromhex(signature_hex))
        return True
    except (nacl.exceptions.BadSignatureError, ValueError, KeyError):
        return False


def sign_registration(
    secret_key_hex: str, name: str, public_key: str, timestamp_ms: Optional[int] = None
) -> RegistrationProof:
    """Build and sign a registration proof-of-possession."""
    ts = timestamp_ms or int(time.time() * 1000)
    payload = {"action": "register", "name": name, "public_key": public_key, "timestamp": ts}
    sig = _sign(secret_key_hex, SIGNATURE_DOMAIN_REGISTER, payload)
    return RegistrationProof(
        name=name,
        public_key=public_key,
        timestamp_ms=ts,
        signature_hex=sig,
    )


def verify_registration(
    proof: RegistrationProof, now_ms: Optional[int] = None
) -> bool:
    """Verify a registration proof is fresh and signed by the claimed key."""
    now = now_ms or int(time.time() * 1000)
    if abs(now - proof.timestamp_ms) > SIGNATURE_FRESHNESS_WINDOW_MS:
        return False
    payload = {
        "action": "register",
        "name": proof.name,
        "public_key": proof.public_key,
        "timestamp": proof.timestamp_ms,
    }
    return _verify(proof.public_key, SIGNATURE_DOMAIN_REGISTER, payload, proof.signature_hex)


def sign_request(
    secret_key_hex: str,
    method: str,
    path: str,
    body: bytes,
    timestamp_ms: Optional[int] = None,
) -> RequestSignature:
    """Sign an HTTP request body."""
    ts = timestamp_ms or int(time.time() * 1000)
    body_hash = hashlib.sha256(body).hexdigest()
    payload = {
        "method": method.upper(),
        "path": path,
        "timestamp": ts,
        "body_sha256": body_hash,
    }
    sig = _sign(secret_key_hex, SIGNATURE_DOMAIN_REQUEST, payload)
    return RequestSignature(
        method=method.upper(),
        path=path,
        timestamp_ms=ts,
        body_sha256_hex=body_hash,
        signature_hex=sig,
    )


def verify_request(
    public_key_hex: str,
    method: str,
    path: str,
    body: bytes,
    timestamp_ms: int,
    signature_hex: str,
    now_ms: Optional[int] = None,
) -> bool:
    """Verify an HTTP request signature is fresh and signed by the claimed key."""
    now = now_ms or int(time.time() * 1000)
    if abs(now - timestamp_ms) > SIGNATURE_FRESHNESS_WINDOW_MS:
        return False
    body_hash = hashlib.sha256(body).hexdigest()
    payload = {
        "method": method.upper(),
        "path": path,
        "timestamp": timestamp_ms,
        "body_sha256": body_hash,
    }
    return _verify(public_key_hex, SIGNATURE_DOMAIN_REQUEST, payload, signature_hex)