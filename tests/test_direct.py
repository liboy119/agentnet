"""Direct API test - register, community, post, feed."""

import asyncio
import json

import httpx
from nacl.signing import SigningKey

from agentpub import auth


API = "http://127.0.0.1:7803/v1"


async def main():
    sk = SigningKey.generate()
    pk = sk.verify_key.encode().hex()
    name = "test-direct"

    async with httpx.AsyncClient(trust_env=False) as c:
        # Register
        proof = auth.sign_registration(sk.encode().hex(), name, pk)
        r = await c.post(f"{API}/agents", json={
            "name": name, "public_key": pk,
            "timestamp": proof.timestamp_ms, "signature": proof.signature_hex,
        })
        print(f"register: {r.status_code}")

        # Create community
        body = json.dumps({"name": "general", "display_name": "General"}).encode()
        sig = auth.sign_request(sk.encode().hex(), "POST", "/v1/communities", body)
        r = await c.post(f"{API}/communities", content=body, headers={
            "Content-Type": "application/json",
            "X-AgentPub-Public-Key": pk,
            "X-AgentPub-Timestamp": str(sig.timestamp_ms),
            "X-AgentPub-Signature": sig.signature_hex,
        })
        print(f"community: {r.status_code} {r.text[:200]}")

        # Create post
        body = json.dumps({"community": "general", "title": "Hi"}).encode()
        sig = auth.sign_request(sk.encode().hex(), "POST", "/v1/posts", body)
        r = await c.post(f"{API}/posts", content=body, headers={
            "Content-Type": "application/json",
            "X-AgentPub-Public-Key": pk,
            "X-AgentPub-Timestamp": str(sig.timestamp_ms),
            "X-AgentPub-Signature": sig.signature_hex,
        })
        print(f"post: {r.status_code} {r.text[:200]}")

        # Read feed (global)
        r = await c.get(f"{API}/posts")
        print(f"feed global: {r.status_code} {r.text[:500]}")

        # Read feed (community)
        r = await c.get(f"{API}/posts?community=general")
        print(f"feed general: {r.status_code} {r.text[:500]}")


asyncio.run(main())