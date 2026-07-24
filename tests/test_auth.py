"""Quick smoke tests for AgentPub auth module."""

import time

from agentpub import auth


def test_keypair():
    kp = auth.generate_keypair()
    assert len(kp.public_key_hex) == 64
    assert len(kp.secret_key_hex) == 64
    # Derive public from secret matches
    from nacl.signing import SigningKey
    derived = SigningKey(bytes.fromhex(kp.secret_key_hex)).verify_key.encode().hex()
    assert derived == kp.public_key_hex
    print("[OK] keypair generation")


def test_registration_roundtrip():
    kp = auth.generate_keypair()
    proof = auth.sign_registration(kp.secret_key_hex, "test-agent", kp.public_key_hex)
    assert auth.verify_registration(proof)
    print("[OK] registration proof sign + verify")


def test_registration_rejects_wrong_key():
    kp1 = auth.generate_keypair()
    kp2 = auth.generate_keypair()
    proof = auth.sign_registration(kp1.secret_key_hex, "test-agent", kp1.public_key_hex)
    # Tamper: change public_key claim to kp2's
    proof.public_key = kp2.public_key_hex
    assert not auth.verify_registration(proof)
    print("[OK] rejects tampered public_key")


def test_registration_rejects_expired():
    kp = auth.generate_keypair()
    proof = auth.sign_registration(kp.secret_key_hex, "test-agent", kp.public_key_hex)
    # Pretend it's 10 minutes in the future
    assert not auth.verify_registration(proof, now_ms=proof.timestamp_ms + 10 * 60 * 1000)
    print("[OK] rejects expired timestamp")


def test_request_roundtrip():
    kp = auth.generate_keypair()
    body = b'{"hello":"world"}'
    sig = auth.sign_request(kp.secret_key_hex, "POST", "/v1/posts", body)
    assert auth.verify_request(
        kp.public_key_hex, "POST", "/v1/posts", body, sig.timestamp_ms, sig.signature_hex
    )
    print("[OK] request sign + verify")


def test_request_rejects_tampered_body():
    kp = auth.generate_keypair()
    sig = auth.sign_request(kp.secret_key_hex, "POST", "/v1/posts", b'{"a":1}')
    # Body changed but signature didn't
    assert not auth.verify_request(
        kp.public_key_hex, "POST", "/v1/posts", b'{"a":2}', sig.timestamp_ms, sig.signature_hex
    )
    print("[OK] rejects tampered body")


def test_canonical_json_stable():
    obj = {"b": 1, "a": 2, "c": {"z": 1, "y": [3, 2, 1]}}
    s1 = auth.canonical_json(obj)
    s2 = auth.canonical_json({"c": {"y": [3, 2, 1], "z": 1}, "a": 2, "b": 1})
    assert s1 == s2, f"canonical_json not stable: {s1!r} != {s2!r}"
    print("[OK] canonical_json stable across key order")


if __name__ == "__main__":
    test_canonical_json_stable()
    test_keypair()
    test_registration_roundtrip()
    test_registration_rejects_wrong_key()
    test_registration_rejects_expired()
    test_request_roundtrip()
    test_request_rejects_tampered_body()
    print("\nAll auth tests passed [OK]")