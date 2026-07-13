from __future__ import annotations

import sys
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_server_lists_expected_tools(self) -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "ae2claude_mcp.server"],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.list_tools()
        names = {tool.name for tool in response.tools}
        self.assertTrue(
            {
                "ae_ping",
                "ae_diagnose",
                "ae_call",
                "ae_effects",
                "ae_add_effect",
                "ae_scripts",
                "ae_run_script",
                "ae_preview_frame",
                "ae_checkpoint",
                "ae_revert",
            }.issubset(names)
        )


if __name__ == "__main__":
    unittest.main()
