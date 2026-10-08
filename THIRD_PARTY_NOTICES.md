# Third-party notices

AE2Claude's MCP layer uses the official Model Context Protocol Python SDK,
distributed under its own license.

The checkpoint, approval, diagnostics, preview, and progressive-tool design was
informed by `JUNKDOGE-JOE/after-effects-mcp` (MIT License). AE2Claude keeps its
existing native AEGP transport and implements these concepts for its own bridge
instead of embedding that project's CEP runtime or panel.

`scripts/json2.jsx` is the unmodified public-domain JSON2 implementation by
Douglas Crockford, dated 2023-05-10, from
[JSON-js](https://github.com/douglascrockford/JSON-js/blob/master/json2.js).
SHA-256: `86df14b56572e68a7e10b18e71804cb78c6890a7d6e534324822c23d12e858a2`.
It is bundled as a local JSX compatibility fallback when the host JSON object
is absent or incomplete. Its original public-domain notice remains in the file.
