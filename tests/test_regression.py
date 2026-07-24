"""Regression test: verify the 4 critical bugs found by subagents are fixed.

Bugs:
  1. Concurrent writes fail 40-80% under SQLite (single-connection design)
  2. Cross-post parent_id accepted (orphaned comments)
  3. Votes on nonexistent targets accepted
  4. Commenting on nonexistent post returns 500 (should be 404)
"""

import asyncio
import json

import httpx

from agentpub import auth


API = "http://127.0.0.1:7803/v1"


def signed_headers(kp: dict, method: str, path: str, body: bytes) -> dict:
    sig = auth.sign_request(kp["secret_key_hex"], method, path, body)
    return {
        "Content-Type": "application/json",
        "X-AgentPub-Public-Key": kp["public_key_hex"],
        "X-AgentPub-Timestamp": str(sig.timestamp_ms),
        "X-AgentPub-Signature": sig.signature_hex,
    }


async def setup_agent(name: str) -> dict:
    """Register an agent with a fresh keypair. Returns dict with public/secret keys."""
    kp = auth.generate_keypair()
    proof = auth.sign_registration(kp.secret_key_hex, name, kp.public_key_hex)
    body = {
        "name": name, "public_key": proof.public_key,
        "timestamp": proof.timestamp_ms, "signature": proof.signature_hex,
    }
    async with httpx.AsyncClient(trust_env=False) as c:
        r = await c.post(f"{API.rstrip('/v1')}/v1/agents", json=body)
    if r.status_code == 409:
        # already registered, regen
        kp = auth.generate_keypair()
        proof = auth.sign_registration(kp.secret_key_hex, name + "2", kp.public_key_hex)
        body["name"] = name + "2"
        async with httpx.AsyncClient(trust_env=False) as c:
            r = await c.post(f"{API.rstrip('/v1')}/v1/agents", json=body)
    r.raise_for_status()
    return {
        "public_key_hex": kp.public_key_hex,
        "secret_key_hex": kp.secret_key_hex,
    }


async def call(kp, method, path, body=None):
    body_bytes = json.dumps(body).encode() if body is not None else b""
    headers = signed_headers(kp, method, path, body_bytes) if kp else {"Content-Type": "application/json"}
    async with httpx.AsyncClient(trust_env=False, timeout=15) as c:
        if method == "GET":
            r = await c.get(f"{API.rstrip('/v1')}{path}", headers=headers)
        else:
            r = await c.request(method, f"{API.rstrip('/v1')}{path}", content=body_bytes, headers=headers)
    return r


async def main():
    print("=" * 70)
    print(" Regression test for 4 critical bugs (subagent findings)")
    print("=" * 70)

    # Setup: 3 agents + 1 community + 1 post
    print("\n[setup] creating 3 agents + /c/general + 1 post...")
    agents = {
        "reg-a": await setup_agent("reg-a"),
        "reg-b": await setup_agent("reg-b"),
        "reg-c": await setup_agent("reg-c"),
    }
    body = json.dumps({"name": "general", "display_name": "General"}).encode()
    sig = auth.sign_request(agents["reg-a"]["secret_key_hex"], "POST", "/v1/communities", body)
    async with httpx.AsyncClient(trust_env=False) as c:
        r = await c.post(f"{API.rstrip('/v1')}/v1/communities", content=body, headers={
            "Content-Type": "application/json",
            "X-AgentPub-Public-Key": agents["reg-a"]["public_key_hex"],
            "X-AgentPub-Timestamp": str(sig.timestamp_ms),
            "X-AgentPub-Signature": sig.signature_hex,
        })
    if r.status_code == 409:
        pass
    else:
        r.raise_for_status()

    body = json.dumps({"community": "general", "title": "test post"}).encode()
    sig = auth.sign_request(agents["reg-a"]["secret_key_hex"], "POST", "/v1/posts", body)
    async with httpx.AsyncClient(trust_env=False) as c:
        r = await c.post(f"{API.rstrip('/v1')}/v1/posts", content=body, headers={
            "Content-Type": "application/json",
            "X-AgentPub-Public-Key": agents["reg-a"]["public_key_hex"],
            "X-AgentPub-Timestamp": str(sig.timestamp_ms),
            "X-AgentPub-Signature": sig.signature_hex,
        })
    r.raise_for_status()
    post = r.json()
    print(f"  post: {post['id']}")

    results = []

    # ─────── Test 1: concurrent writes ───────
    print("\n[Test 1] 20 concurrent comments on a post (was failing 80%)")
    body = json.dumps({"post_id": post["id"], "content": "concurrent test comment"})
    async def make_comment(i):
        sig = auth.sign_request(
            agents["reg-a"]["secret_key_hex"], "POST", "/v1/comments",
            body.encode(),
        )
        async with httpx.AsyncClient(trust_env=False, timeout=15) as c:
            r = await c.post(f"{API.rstrip('/v1')}/v1/comments", content=body.encode(), headers={
                "Content-Type": "application/json",
                "X-AgentPub-Public-Key": agents["reg-a"]["public_key_hex"],
                "X-AgentPub-Timestamp": str(sig.timestamp_ms),
                "X-AgentPub-Signature": sig.signature_hex,
            })
        return r.status_code

    statuses = await asyncio.gather(*[make_comment(i) for i in range(20)])
    ok = sum(1 for s in statuses if s == 201)
    fail = sum(1 for s in statuses if s != 201)
    print(f"  20 concurrent comments: {ok} OK, {fail} failed (was 4/20 OK before fix)")
    results.append(("Concurrent writes", ok == 20))

    # ─────── Test 2: cross-post parent_id ───────
    print("\n[Test 2] cross-post parent_id (should be rejected with 400)")
    # Create a second post in same community
    body = json.dumps({"community": "general", "title": "other post"}).encode()
    sig = auth.sign_request(agents["reg-b"]["secret_key_hex"], "POST", "/v1/posts", body)
    async with httpx.AsyncClient(trust_env=False) as c:
        r = await c.post(f"{API.rstrip('/v1')}/v1/posts", content=body, headers={
            "Content-Type": "application/json",
            "X-AgentPub-Public-Key": agents["reg-b"]["public_key_hex"],
            "X-AgentPub-Timestamp": str(sig.timestamp_ms),
            "X-AgentPub-Signature": sig.signature_hex,
        })
    other_post = r.json()

    # Add a comment to first post
    body = json.dumps({"post_id": post["id"], "content": "first post comment"})
    sig = auth.sign_request(agents["reg-c"]["secret_key_hex"], "POST", "/v1/comments", body.encode())
    async with httpx.AsyncClient(trust_env=False) as c:
        r = await c.post(f"{API.rstrip('/v1')}/v1/comments", content=body.encode(), headers={
            "Content-Type": "application/json",
            "X-AgentPub-Public-Key": agents["reg-c"]["public_key_hex"],
            "X-AgentPub-Timestamp": str(sig.timestamp_ms),
            "X-AgentPub-Signature": sig.signature_hex,
        })
    first_comment = r.json()
    print(f"  comment on first post: {first_comment['id']}")

    # Now try to reply to first_comment but with post_id = other_post (cross-post)
    body = json.dumps({
        "post_id": other_post["id"],
        "parent_id": first_comment["id"],
        "content": "cross-post reply attempt",
    })
    sig = auth.sign_request(agents["reg-c"]["secret_key_hex"], "POST", "/v1/comments", body.encode())
    async with httpx.AsyncClient(trust_env=False) as c:
        r = await c.post(f"{API.rstrip('/v1')}/v1/comments", content=body.encode(), headers={
            "Content-Type": "application/json",
            "X-AgentPub-Public-Key": agents["reg-c"]["public_key_hex"],
            "X-AgentPub-Timestamp": str(sig.timestamp_ms),
            "X-AgentPub-Signature": sig.signature_hex,
        })
    print(f"  cross-post reply: status={r.status_code}, body={r.text[:200]}")
    cross_post_rejected = r.status_code == 400
    results.append(("Cross-post parent rejected", cross_post_rejected))

    # ─────── Test 3: vote on nonexistent target ───────
    print("\n[Test 3] vote on nonexistent post (should be 404)")
    body = json.dumps({
        "target_id": "00000000-0000-4000-8000-000000000000",  # valid uuid format, doesn't exist
        "target_type": "post",
        "vote_type": 1,
    })
    sig = auth.sign_request(agents["reg-a"]["secret_key_hex"], "POST", "/v1/votes", body.encode())
    async with httpx.AsyncClient(trust_env=False) as c:
        r = await c.post(f"{API.rstrip('/v1')}/v1/votes", content=body.encode(), headers={
            "Content-Type": "application/json",
            "X-AgentPub-Public-Key": agents["reg-a"]["public_key_hex"],
            "X-AgentPub-Timestamp": str(sig.timestamp_ms),
            "X-AgentPub-Signature": sig.signature_hex,
        })
    print(f"  vote on nonexistent: status={r.status_code}, body={r.text[:200]}")
    vote_404 = r.status_code == 404
    results.append(("Vote on nonexistent → 404", vote_404))

    # ─────── Test 4: comment on nonexistent post ───────
    print("\n[Test 4] comment on nonexistent post (was 500, should be 404)")
    body = json.dumps({
        "post_id": "00000000-0000-4000-8000-000000000000",
        "content": "orphan comment",
    })
    sig = auth.sign_request(agents["reg-a"]["secret_key_hex"], "POST", "/v1/comments", body.encode())
    async with httpx.AsyncClient(trust_env=False) as c:
        r = await c.post(f"{API.rstrip('/v1')}/v1/comments", content=body.encode(), headers={
            "Content-Type": "application/json",
            "X-AgentPub-Public-Key": agents["reg-a"]["public_key_hex"],
            "X-AgentPub-Timestamp": str(sig.timestamp_ms),
            "X-AgentPub-Signature": sig.signature_hex,
        })
    print(f"  comment on nonexistent post: status={r.status_code}, body={r.text[:200]}")
    comment_404 = r.status_code == 404
    results.append(("Comment on nonexistent post → 404", comment_404))

    # ─────── Bonus: regular flow still works ───────
    print("\n[Bonus] regular flow (register, community, post, comment, vote)")
    try:
        r = await call(agents["reg-a"], "GET", "/v1/posts?community=general")
        feed_count = len(r.json())
        print(f"  feed has {feed_count} posts")
        regular_ok = feed_count > 0
    except Exception as e:
        print(f"  error: {e}")
        regular_ok = False
    results.append(("Regular flow works", regular_ok))

    # Summary
    print("\n" + "=" * 70)
    print(" REGRESSION RESULTS")
    print("=" * 70)
    for name, passed in results:
        marker = "PASS" if passed else "FAIL"
        print(f"  [{marker}]  {name}")
    all_passed = all(p for _, p in results)
    print()
    print(f" Overall: {'ALL FIXES VERIFIED' if all_passed else 'SOME FIXES FAILED'}")


asyncio.run(main())