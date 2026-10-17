# AE MCP over Tailscale

This optional transport reuses the existing MCP server and all AE safety
checks. Local stdio clients and the native bridge at 127.0.0.1:18889 are unchanged.

`ae_capture_blocked_ui` also returns inline images of confirmed AE modal dialogs
through this same authenticated endpoint. See [blocked UI capture](BLOCKED_UI_CAPTURE.md)
for the on-demand workflow, image limits and recovery boundaries.
No Adobe binary reinstall is needed. The native bridge is never exposed remotely.

## Access model

Tailscale Serve terminates private HTTPS and supplies authenticated identity
headers. The backend listens only on 127.0.0.1:18890 and accepts one configured
Tailscale user login and exact hostname. Missing, duplicate, or other identities,
browser Origin/Sec-Fetch requests and non-loopback backend peers are denied.
Uvicorn proxy header interpretation is disabled. **Do not expose this backend
directly or place another proxy in front of it. Never enable Funnel.**

All devices logged in as the configured owner can use this endpoint, subject to
tailnet access rules. Tagged or differently owned cloud nodes are denied. Same-user
local processes retain their existing ability to use stdio and the native bridge.
This is a privileged AE execution interface, not a public or multi-user service.
Tools retain `auto` mode: ordinary writes are enabled; destructive calls require
their existing `confirm=true`. HTTP is stateless to avoid cross-client session reuse.

## Install

From this repository, with its existing .venv, run:

```powershell
pwsh -File tools/tailnet-service.ps1 Install -Hostname YOUR-PC.YOUR-TAILNET.ts.net -AllowedLogin YOUR-TAILSCALE-LOGIN
tailscale serve --bg --https=443 http://127.0.0.1:18890
```

Inspect `tailscale serve status --json` first. Do not overwrite another service's
443 configuration. HTTPS must already be enabled or enabled by the tailnet owner.
No exit node, DNS, subnet route, or VPN settings need changing.

The named Windows task `AE2Claude-Tailnet` starts hidden at user sign-in, prevents
duplicate instances and retries failures three times, one minute apart. It uses
the existing project's Python runtime, not a temporary downloaded launcher.
It does not launch AE automatically. Open AE Beta normally or with the workbench
safe start script. Tools stay discoverable while AE is closed; `ae_ping` then
reports `state: offline`, not success.

Config: `state/tailnet-mcp.json`. Logs: `state/tailnet-mcp.log`, rotating at 1 MiB
with three backups. Request bodies and credentials are not logged.

## Client

Use Streamable HTTP, not legacy SSE, from a host joined to the same tailnet:

```json
{"mcpServers":{"ae-windows":{"url":"https://YOUR-PC.YOUR-TAILNET.ts.net/mcp"}}}
```

No bearer token or separate OAuth flow is needed; authorization comes from the
host's Tailscale identity. If an application routes MCP requests through its own
cloud gateway, that gateway must also have private-network access. A terminal's
successful curl does not establish that a separately hosted MCP gateway can reach it.
Use a local MCP client or stdio adapter on the joined cloud host in that case.
Remote file paths refer to Windows; transfer assets separately before using them.

If an existing VPN resolves `*.ts.net` to a FakeIP range, compare that result with
`tailscale status --json`. For a one-off diagnostic, curl's `--resolve` can pin the
exact hostname to the node's Tailscale address while still checking its HTTPS
certificate. Do not disable certificate validation or change global VPN/DNS settings.

Verify initialization, tool listing, `ae_ping` and a read-only project inspection
from the real consumer. Avoid JSX/render/write tests against the user's project.

## Stop / restore / uninstall

```powershell
pwsh -File tools/tailnet-service.ps1 Status
pwsh -File tools/tailnet-service.ps1 Stop
pwsh -File tools/tailnet-service.ps1 Start
# Remove only this task; preserve config/logs:
pwsh -File tools/tailnet-service.ps1 Remove
# Remove its private HTTPS listener if still dedicated to this service:
tailscale serve --https=443 off
```

Stopping disables future logon launches and stops the owned task. Existing local
stdio MCP and AE remain operational. Do not use `tailscale serve reset`, which
could remove unrelated services added later.

References: [Tailscale Serve and identity headers](https://tailscale.com/docs/features/tailscale-serve),
[MCP Streamable HTTP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).
