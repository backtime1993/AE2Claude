import unittest
from ae2claude_mcp.tailnet import TailnetIdentityGate


class TailnetGateTests(unittest.IsolatedAsyncioTestCase):
    async def request(self, *, peer="127.0.0.1", host="desktop.test.ts.net", login="owner@example.com", extra=()):
        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})
        gate = TailnetIdentityGate(app, hostname="desktop.test.ts.net", login="owner@example.com")
        headers = [(b"host", host.encode())]
        if login is not None:
            headers.append((b"tailscale-user-login", login.encode()))
        messages = []
        async def send(message):
            messages.append(message)
        async def receive():
            return {"type": "http.request", "body": b""}
        await gate({"type": "http", "method": "POST", "headers": headers + list(extra), "client": (peer, 123)}, receive, send)
        return messages[0]["status"]

    async def test_authorized_serve_request(self):
        self.assertEqual(await self.request(), 204)
        self.assertEqual(await self.request(host="desktop.test.ts.net:443"), 204)

    async def test_missing_or_other_identity(self):
        for login in (None, "", "other@example.com"):
            self.assertEqual(await self.request(login=login), 403)

    async def test_remote_cannot_spoof_serve(self):
        self.assertEqual(await self.request(peer="100.64.0.10"), 403)

    async def test_invalid_host(self):
        self.assertEqual(await self.request(host="evil.example"), 403)

    async def test_browser_requests_rejected(self):
        for header in (b"origin", b"sec-fetch-site"):
            self.assertEqual(await self.request(extra=[(header, b"https://desktop.test.ts.net")]), 403)

    async def test_duplicate_identity_or_host_rejected(self):
        for key, value in ((b"tailscale-user-login", b"owner@example.com"), (b"host", b"desktop.test.ts.net")):
            self.assertEqual(await self.request(extra=[(key, value)]), 403)


if __name__ == "__main__":
    unittest.main()
