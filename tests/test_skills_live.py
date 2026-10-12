"""Opt-in read-only acceptance; never creates fixtures or changes AE focus."""
from __future__ import annotations

import os
import unittest

from ae2claude_mcp.runtime import bridge
from ae2claude_mcp.skills import prepare_skill, run_skill


@unittest.skipUnless(os.environ.get("AE2CLAUDE_SKILL_LIVE_TEST") == "1", "requires a running AE; read-only Skill acceptance")
class SkillLiveTests(unittest.TestCase):
    def state(self):
        with bridge() as ae:
            info = ae.get_connection_info()
            comp = ae.comp_info()
            return {"project": info.get("project"), "dirty": info.get("projectDirty"),
                    "comp": comp, "selection": ae.get_selected_layers() if comp else []}

    def test_preflight_collector_and_report_preserve_project(self):
        before = self.state()
        with bridge() as ae:
            data = ae.get_preflight_snapshot()
        self.assertTrue(data["ok"])
        self.assertIn("expressionVisited", data)
        result = run_skill("/pv-preflight")
        self.assertTrue(result["report"]["readOnly"])
        self.assertEqual(before, self.state())

    def test_motion_review_preserves_project_and_exposes_missing_comp(self):
        before = self.state()
        report = run_skill("/motion-review")["report"]
        if not before["comp"]:
            self.assertEqual(report["status"], "incomplete")
            self.assertTrue(report["limitations"])
        else:
            self.assertIn("compId", report["coverage"])
        self.assertEqual(before, self.state())

    def test_agent_bundle_captures_live_context(self):
        before = self.state()
        result = prepare_skill("/pv-preflight")
        self.assertTrue(result["context"]["captured"])
        self.assertEqual(result["context"]["comp"], before["comp"])
        self.assertEqual(before, self.state())
