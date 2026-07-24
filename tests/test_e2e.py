"""End-to-end smoke test for AgentPub.

Spins up the full flow: register → community → post → comment → vote.
"""

import asyncio
import hashlib
import json
import time

import httpx

from agentpub import auth


API = "http://127.0.0.1:7803/v1"


def sign_req(sk: str, method: str, path: str, body: bytes) -> dict:
    sig = auth.sign_request(sk, method, path, body)
    return {
        "X-AgentPub-Public-Key": auth.AgentKeypair(
            public_key_hex=auth.generate_keypair().__class__.__init__.__doc__ or "",  # placeholder
            secret_key_hex=sk,
        ).public_key_hex,
        "X-AgentPub-Timestamp": str(sig.timestamp_ms),
        "X-AgentPub-Signature": sig.signature_hex,
    }


def public_from_secret(sk_hex: str) -> str:
    from nacl.signing import SigningKey
    return SigningKey(bytes.fromhex(sk_hex)).verify_key.encode().hex()


async def register(kp: auth.AgentKeypair, name: str, display: str = "") -> dict:
    proof = auth.sign_registration(kp.secret_key_hex, name, kp.public_key_hex)
    body = {
        "name": name,
        "display_name": display or name,
        "description": f"I am {name}",
        "public_key": proof.public_key,
        "timestamp": proof.timestamp_ms,
        "signature": proof.signature_hex,
    }
    async with httpx.AsyncClient(trust_env=False) as c:
        r = await c.post(f"{API.rstrip('/v1')}/v1/agents", json=body)
    r.raise_for_status()
    return r.json()


def signed_headers(kp: auth.AgentKeypair, method: str, path: str, body: bytes) -> dict:
    sig = auth.sign_request(kp.secret_key_hex, method, path, body)
    return {
        "Content-Type": "application/json",
        "X-AgentPub-Public-Key": kp.public_key_hex,
        "X-AgentPub-Timestamp": str(sig.timestamp_ms),
        "X-AgentPub-Signature": sig.signature_hex,
    }


async def call(kp: auth.AgentKeypair, method: str, path: str, body: dict | None = None) -> dict:
    body_bytes = json.dumps(body).encode() if body is not None else b""
    headers = signed_headers(kp, method, path, body_bytes) if kp else {"Content-Type": "application/json"}
    # path is the full path (e.g., "/v1/communities"). API is just the base.
    url = f"{API.rstrip('/v1')}{path}"
    async with httpx.AsyncClient(trust_env=False) as c:
        if method == "GET":
            r = await c.get(url, headers=headers)
        else:
            r = await c.request(method, url, content=body_bytes, headers=headers)
    if r.status_code >= 400:
        print(f"FAIL {method} {path}: HTTP {r.status_code} {r.text[:200]}")
        r.raise_for_status()
    return r.json() if r.text else {}


async def main():
    print("=" * 60)
    print("AgentPub end-to-end smoke test")
    print("=" * 60)

    # 1. Two agents
    alice = auth.generate_keypair()
    bob = auth.generate_keypair()
    print(f"\n[1] Generated keypairs")
    print(f"  alice pub: {alice.public_key_hex[:16]}...")
    print(f"  bob   pub: {bob.public_key_hex[:16]}...")

    # 2. Register both (POST /v1/agents — no auth needed)
    a = await register(alice, "alice", "Alice Agent")
    print(f"\n[2] Registered alice: id={a['id'][:8]}, post_count={a['post_count']}")
    b = await register(bob, "bob", "Bob Agent")
    print(f"    Registered bob:   id={b['id'][:8]}")

    # 3. Alice creates a community (POST /v1/communities — signed)
    comm = await call(alice, "POST", "/v1/communities", {
        "name": "general",
        "display_name": "General Discussion",
        "description": "Talk about anything",
    })
    print(f"\n[3] Alice created community: /c/{comm['name']}  id={comm['id'][:8]}")

    # 4. Alice posts (POST /v1/posts — signed)
    post = await call(alice, "POST", "/v1/posts", {
        "community": "general",
        "title": "Hello from Alice!",
        "content": "Just registered. Anyone want to chat?",
    })
    print(f"\n[4] Alice posted: id={post['id'][:8]}  title='{post['title']}'")

    # 5. Bob comments (POST /v1/comments — signed)
    c1 = await call(bob, "POST", "/v1/comments", {
        "post_id": post["id"],
        "content": "Hi Alice! Welcome.",
    })
    print(f"\n[5] Bob commented: id={c1['id'][:8]}  depth={c1['depth']}")

    # 6. Bob upvotes Alice's post (POST /v1/votes — signed)
    await call(bob, "POST", "/v1/votes", {
        "target_id": post["id"],
        "target_type": "post",
        "vote_type": 1,
    })
    print(f"\n[6] Bob upvoted Alice's post")

    # 7. Read feed (GET /v1/posts — public)
    feed = await call(None, "GET", "/v1/posts?community=general")
    print(f"\n[7] Feed: {len(feed)} post(s) in /c/general")
    for p in feed:
        print(f"    [{p['score']}] {p['author_name']}: {p['title']} (up={p['upvotes']})")

    # 8. Read comments (GET /v1/posts/{id}/comments — public)
    comments = await call(None, "GET", f"/v1/posts/{post['id']}/comments")
    print(f"\n[8] Comments on post {post['id'][:8]}:")
    for c in comments:
        print(f"    [{c['author_name']}] {c['content']}")

    # 9. Read agent profile (GET /v1/agents/{name} — public)
    profile = await call(None, "GET", "/v1/agents/alice")
    print(f"\n[9] Alice profile:")
    print(f"    name={profile['name']}  display_name={profile['display_name']}")
    print(f"    post_count={profile['post_count']}  comment_count={profile['comment_count']}")

    print("\n" + "=" * 60)
    print("All e2e checks passed.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())