from __future__ import annotations

import json
import os
import tempfile
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ae2claude_mcp import skills
from ae2claude_mcp.cli import build_parser, dispatch
from ae2claude_mcp.runtime import SafetyError
from ae2claude_mcp.skill_reports import PREFLIGHT_JSX, QC_TARGETS_JSX, preflight_snapshot, qc_targets, review_keyframes, run_motion_review, run_preflight


class SkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project, self.user = self.root / "project", self.root / "user"
        self.project.mkdir()
        self.user.mkdir()

    def write(self, parent=None, name="review", extra="", body="Inspect only."):
        folder = (parent or self.project / "skills") / name
        folder.mkdir(parents=True, exist_ok=True)
        file = folder / "SKILL.md"
        file.write_text(f'---\nname: {name}\ndescription: Review animation\n{extra}---\n{body}\n', encoding="utf-8")
        return file

    def load(self, name="review"):
        return skills.load_skill(name, str(self.project), str(self.user))

    def test_defaults_are_read_only_with_no_tools(self):
        self.write()
        skill = self.load()
        self.assertTrue(skill.read_only)
        self.assertEqual(skill.allowed_tools, ())
        self.assertEqual(skill.version, "1.0.0")

    def test_yaml_multiline_and_version(self):
        file = self.write(extra='version: "2.1.0"\nallowed_tools:\n  - project_info\nrequires: [project_info]\n')
        self.assertEqual(self.load().version, "2.1.0")
        self.assertEqual(self.load().allowed_tools, ("project_info",))
        self.assertEqual(self.load().sha256, __import__("hashlib").sha256(file.read_bytes()).hexdigest())

    def test_project_overrides_user_overrides_bundled(self):
        self.write(self.user, "pv-preflight", body="user")
        self.assertEqual(self.load("pv-preflight").instructions, "user")
        self.write(name="pv-preflight", body="project")
        self.assertEqual(self.load("pv-preflight").instructions, "project")
        self.assertEqual(self.load("motion-review").source, "builtin")

    def test_equivalent_hidden_project_directory(self):
        self.write(self.project / ".ae2claude" / "skills")
        self.assertEqual(self.load().source, "project")

    def test_invalid_override_does_not_fall_back(self):
        path = self.write(name="pv-preflight")
        path.write_text("invalid", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid Skill"):
            self.load("pv-preflight")
        discovery = skills.discover_skills(str(self.project), str(self.user))
        self.assertFalse(discovery["ok"])
        self.assertEqual(discovery["errors"][0]["name"], "pv-preflight")

    def test_fail_closed_metadata(self):
        for extra in ('read_only: "false"\n', 'read_only: true\nread_only: false\n',
                      'allowed_tools: "*"\n', 'allowed_tools: [run_jsx]\n',
                      'allowed_tools: [not_real]\n', 'requires: [project_info]\n',
                      'read-only: false\n', 'version: 3\n',
                      'allowed_tools: !!python/object/apply:os.system [echo]\n'):
            with self.subTest(extra=extra):
                self.write(extra=extra)
                with self.assertRaises((ValueError, SafetyError)):
                    self.load()

    def test_unknown_and_traversal_commands(self):
        for command in ("/../review", "/a/b", "/", "missing"):
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.load(command)

    def test_discovery_is_offline_and_does_not_return_body(self):
        self.write(body="UNIQUE_LONG_INSTRUCTIONS")
        with patch.object(skills, "bridge") as bridge:
            result = skills.discover_skills(str(self.project), str(self.user))
        bridge.assert_not_called()
        self.assertNotIn("UNIQUE_LONG_INSTRUCTIONS", json.dumps(result))

    def test_prepare_context_and_schemas(self):
        self.write(extra="allowed_tools: [project_info]\n")
        ae = Mock()
        ae.__enter__ = Mock(return_value=ae)
        ae.__exit__ = Mock(return_value=False)
        ae.project_info.return_value = {"file": "pv.aep"}
        ae.comp_info.return_value = {"id": 7}
        ae.get_selected_layers.return_value = []
        with patch.object(skills, "bridge", return_value=ae):
            result = skills.prepare_skill("/review titles", str(self.project), str(self.user))
        self.assertEqual(result["request"], "titles")
        self.assertTrue(result["context"]["captured"])
        self.assertEqual([x["name"] for x in result["tools"]], ["project_info"])
        self.assertEqual(result["execution"]["expected_sha256"], self.load().sha256)

    def test_offline_context_is_explicit(self):
        self.write()
        with patch.object(skills, "bridge", side_effect=ConnectionError("offline")):
            result = skills.prepare_skill("review", str(self.project), str(self.user))
        self.assertFalse(result["context"]["captured"])
        self.assertIn("offline", result["context"]["error"])

    def test_empty_project_context_does_not_query_invalid_selection(self):
        self.write()
        ae = Mock()
        ae.__enter__ = Mock(return_value=ae)
        ae.__exit__ = Mock(return_value=False)
        ae.project_info.return_value = {"numItems": 0, "file": "unsaved"}
        ae.comp_info.return_value = {}
        ae.get_selected_layers.side_effect = AssertionError("no active comp")
        with patch.object(skills, "bridge", return_value=ae):
            result = skills.prepare_skill("review", str(self.project), str(self.user))
        self.assertTrue(result["context"]["captured"])
        self.assertEqual(result["context"]["selectedLayers"], [])
        ae.get_selected_layers.assert_not_called()

    def test_denied_batch_never_dispatches_even_in_bypass_mode(self):
        self.write(extra="allowed_tools: [project_info]\n")
        ops = [{"method": "project_info"}, {"method": "run_jsx", "args": ["app.project.close()"]}]
        with patch.dict(os.environ, {"AE2CLAUDE_APPROVAL_MODE": "bypass"}), patch.object(skills, "execute_batch") as execute:
            with self.assertRaises(SafetyError):
                skills.execute_skill("review", ops, self.load().sha256, str(self.project), str(self.user), confirm=True)
        execute.assert_not_called()

    def test_changed_file_hash_prevents_dispatch(self):
        path = self.write(extra="allowed_tools: [project_info]\n")
        digest = self.load().sha256
        path.write_text(path.read_text() + "Changed", encoding="utf-8")
        with patch.object(skills, "execute_batch") as execute, self.assertRaisesRegex(SafetyError, "changed"):
            skills.execute_skill("review", [{"method": "project_info"}], digest, str(self.project), str(self.user))
        execute.assert_not_called()

    def test_execution_skill_requires_confirm_and_preserves_global_policy(self):
        self.write(extra="read_only: false\nallowed_tools: [rename_layer]\n")
        skill = self.load()
        ops = [{"method": "rename_layer", "args": ["old", "new"]}]
        with patch.object(skills, "execute_batch") as execute:
            with self.assertRaises(SafetyError):
                skills.execute_skill("review", ops, skill.sha256, str(self.project), str(self.user))
            execute.assert_not_called()
            execute.return_value = {"ok": True}
            skills.execute_skill("review", ops, skill.sha256, str(self.project), str(self.user), confirm=True)
            self.assertTrue(execute.call_args.kwargs["confirm"])
        with patch.dict(os.environ, {"AE2CLAUDE_APPROVAL_MODE": "readonly"}), patch("ae2claude_mcp.agent_runtime.bridge") as bridge:
            with self.assertRaises(SafetyError):
                skills.execute_skill("review", ops, skill.sha256, str(self.project), str(self.user), confirm=True)
        bridge.assert_not_called()

    def test_custom_skill_cannot_select_bundled_runner_by_name(self):
        self.write(name="pv-preflight", body="execute arbitrary code")
        with self.assertRaisesRegex(ValueError, "no bundled runner"):
            skills.run_skill("pv-preflight", str(self.project), str(self.user))

    def test_cli_discovery_and_offline_slash_invocation(self):
        parser = build_parser()
        with patch.object(skills, "bridge") as bridge:
            result = dispatch(parser.parse_args(["skill", "/motion-review", "--offline",
                "--project-dir", str(self.project), "--user-dir", str(self.user)]))
        bridge.assert_not_called()
        self.assertEqual(result["skill"]["name"], "motion-review")


class ReportTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "requires Node for fixed JSX collector contract")
    def test_fixed_jsx_collectors_cover_inactive_comps_without_mutations(self):
        # Execute the actual collector source against a small AE DOM fixture.
        # Setter traps enforce the no-time/no-focus/no-work-area contract.
        harness = r'''
const vm = require('vm'), fs = require('fs');
const code = fs.readFileSync(0, 'utf8');
class CompItem { constructor(id) { Object.assign(this,{id,name:'PV'+id,frameRate:30,duration:3,
 width:1920,height:1080,pixelAspect:1,numLayers:1,workAreaDuration:3});
 Object.defineProperty(this,'time',{get(){return id},set(){throw Error('time changed')}});
 Object.defineProperty(this,'workAreaStart',{get(){return 0},set(){throw Error('work area changed')}}); }
 layer(){return {id:this.id*10,solo:false,numProperties:1,property(){return {
  name:'Position',matchName:'ADBE Position',numKeys:2,numProperties:0,canSetExpression:true,
  expression:'broken',expressionEnabled:true,expressionError:'broken reference',
  valueAtTime(t){if(t!==1&&t!==2)throw Error('unexpected sample time');return 0;}};}};}}
class FootageItem { constructor(){Object.assign(this,{id:3,name:'missing',file:{fsName:'gone.png'},
 footageMissing:true,usedIn:[],proxySource:null});}}
const comps=[new CompItem(1),new CompItem(2)],items=[...comps,new FootageItem()];
const project={file:null,dirty:false,numItems:items.length,item(i){return items[i-1]},
 workingSpace:'None',bitsPerChannel:8,linearBlending:false,
 usedFonts:[{font:{postScriptName:'MissingFont',isSubstitute:true}}],renderQueue:{numItems:0}};
Object.defineProperty(project,'activeItem',{get(){return comps[0]},set(){throw Error('focus changed')}});
console.log(vm.runInNewContext(code,{app:{project},CompItem,FootageItem,PropertyType:{INDEXED_GROUP:2}}, {timeout:1000}));
'''
        cfg = {"maxItems": 20, "maxProperties": 100}
        result = subprocess.run([shutil.which("node"), "-e", harness], input=PREFLIGHT_JSX.replace("SETTINGS", json.dumps(cfg)),
                                capture_output=True, text=True, timeout=10, check=True)
        data = json.loads(result.stdout)
        self.assertEqual({x["compId"] for x in data["expressionErrors"]}, {1, 2})
        self.assertEqual(data["expressionEvaluated"], 2)
        self.assertTrue(data["fonts"][0]["missing"])
        self.assertTrue(data["footage"][0]["missing"])
        cfg = {"compId": 2, "maxProperties": 10, "maxNodes": 100}
        result = subprocess.run([shutil.which("node"), "-e", harness], input=QC_TARGETS_JSX.replace("SETTINGS", json.dumps(cfg)),
                                capture_output=True, text=True, timeout=10, check=True)
        data = json.loads(result.stdout)
        self.assertEqual(data["compId"], 2)
        self.assertEqual(data["targets"][0]["layerId"], 20)
        self.assertEqual(data["targets"][0]["path"], ["ADBE Position"])

    def test_preflight_project_wide_findings_and_limits(self):
        data = {"project": {"file": None, "workingSpace": "sRGB"}, "truncated": True,
                "comps": [{"id": 1, "name": "Comp 1", "fps": 12, "duration": 3,
                           "workAreaDuration": 1, "soloLayers": [7], "numLayers": 1}],
                "footage": [{"id": 4, "missing": True, "unused": True}],
                "fonts": [{"name": "missing", "missing": True}],
                "outputs": [{"path": "gone/file.mp4", "parentExists": False}],
                "expressionErrors": [{"compId": 2, "error": "undefined reference"}]}
        call = Mock(return_value=data)
        report = run_preflight(call, {"expected_working_space": "ACES"})
        self.assertEqual(report["status"], "incomplete")
        self.assertTrue(report["readOnly"])
        codes = {f["code"] for f in report["findings"]}
        self.assertTrue({"frame-rate", "missing-footage", "missing-font", "expression-error",
                         "working-space", "output-path", "solo-layers"} <= codes)
        self.assertEqual(call.call_args.args, ("get_preflight_snapshot",))

    def test_unavailable_collector_never_claims_pass(self):
        report = run_preflight(Mock(side_effect=RuntimeError("offline")), {})
        self.assertEqual(report["status"], "incomplete")

    def test_configured_24fps_is_not_a_problem(self):
        data = {"project": {"file": "pv.aep", "workingSpace": "sRGB"}, "comps": [
            {"id": 1, "name": "PV", "fps": 24, "duration": 3}],
            "outputs": [{"path": "pv.mp4", "parentExists": True}]}
        report = run_preflight(Mock(return_value=data), {"allowed_fps": [24]})
        self.assertEqual(report["status"], "pass")

    def test_native_fraction_ease_and_heuristics(self):
        keys = [
            {"index": 0, "time": 0, "inInterpolation": 1, "outInterpolation": 1},
            {"index": 1, "time": 1/30, "inInterpolation": 2, "outInterpolation": 2,
             "temporalEase": [[0, .333, 0, .333]], "spatialTangents": [[1,0],[0,1]]}]
        codes = {x["code"] for x in review_keyframes(keys, 30, {"layerId": 7})}
        self.assertTrue({"dense-keys", "segment-ease-mismatch", "spatial-corner"} <= codes)
        self.assertNotIn("ease-influence", codes)
        keys[1]["temporalEase"] = [[0, 33.3, 0, 33.3]]
        self.assertIn("ease-influence", {x["code"] for x in review_keyframes(keys,30,{})})

    def test_motion_unavailable_and_truncated_streams(self):
        targets = {"compId": 4, "fps": 30, "targets": [
            {"layerId": 7, "path": ["x"]}, {"layerId": 8, "path": ["y"]}], "truncated": True}
        call = Mock(side_effect=[targets, {"keyframes": [], "truncated": True}, RuntimeError("unsupported")])
        report = run_motion_review(call, {})
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["coverage"]["propertiesReviewed"], 1)
        self.assertEqual(call.call_args_list[1].args[0], "get_native_keyframes")

    def test_collector_limits_checked_before_jsx(self):
        ae = Mock()
        for run, args in ((preflight_snapshot, {"max_items": True}),
                          (qc_targets, {"comp_id": -1}), (qc_targets, {"max_nodes": 0})):
            with self.assertRaises(ValueError):
                run(ae, **args)
        ae.run_jsx.assert_not_called()


if __name__ == "__main__":
    unittest.main()
