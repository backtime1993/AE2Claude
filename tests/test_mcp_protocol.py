from __future__ import annotations

import sys
import os
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
                "ae_preview_frames",
                "ae_compare_frames",
                "ae_script_library",
                "ae_replay_script",
                "ae_native_status",
                "ae_native_snapshot",
                "ae_sample_property",
                "ae_native_keyframes",
                "ae_set_native_keyframes",
                "ae_layer_transforms",
                "ae_validate_expressions",
                "ae_checkpoint",
                "ae_revert",
                "ae_capabilities",
                "ae_inspect_properties",
                "ae_property_batch",
                "ae_batch",
                "ae_submit",
                "ae_task",
                "ae_events",
            }.issubset(names)
        )

    @unittest.skipUnless(
        os.environ.get("AE2CLAUDE_LIVE_TEST") == "1",
        "set AE2CLAUDE_LIVE_TEST=1 with AE running",
    )
    async def test_stdio_server_reaches_live_ae27(self) -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "ae2claude_mcp.server"],
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.call_tool("ae_ping")
        payload = response.structuredContent
        self.assertIsNotNone(payload)
        self.assertEqual(payload["serverVersion"], "4.3.1")
        self.assertTrue(payload["bridge"]["connected"], payload["bridge"])
        self.assertTrue(str(payload["bridge"]["aeVersion"]).startswith("27."))


if __name__ == "__main__":
    unittest.main()
