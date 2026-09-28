"""Run against a rebuilt AEX; SDK-independent tests cannot prove AE behavior."""
import json
import os
import unittest

from ae_bridge import AEBridge


@unittest.skipUnless(os.environ.get("AE2CLAUDE_LIVE_TEST") == "1",
                     "requires a running AE acceptance instance")
class NativeLayerControlsAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.ae = AEBridge()
        self.addCleanup(self.ae.close)
        state = json.loads(self.ae.run_jsx(
            'JSON.stringify({items:app.project.numItems,file:app.project.file?app.project.file.fsName:null})'))
        if state["items"] or state["file"]:
            self.skipTest("requires an empty unsaved acceptance project")
        self.addCleanup(self.ae.run_jsx,
                        'app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);app.newProject(); "clean"')
        self.ids = json.loads(self.ae.run_jsx('''(function(){
            var c=app.project.items.addComp("native blend acceptance",320,180,1,2,30);
            var solid=c.layers.addSolid([.3,.4,.5],"solid",320,180,1);
            var text=c.layers.addText("blend");
            var shape=c.layers.addShape();
            shape.property("ADBE Root Vectors Group").addProperty("ADBE Vector Shape - Rect");
            shape.property("ADBE Root Vectors Group").addProperty("ADBE Vector Graphic - Fill");
            var matte=c.layers.addSolid([1,1,1],"matte",320,180,1);
            shape.setTrackMatte(matte,TrackMatteType.ALPHA);
            text.preserveTransparency=true;
            var camera=c.layers.addCamera("camera",[160,90]);
            var light=c.layers.addLight("light",[160,90]);
            return JSON.stringify({comp:c.id,solid:solid.id,text:text.id,shape:shape.id,
                camera:camera.id,light:light.id,modes:{normal:Number(BlendingMode.NORMAL),
                add:Number(BlendingMode.ADD),multiply:Number(BlendingMode.MULTIPLY),
                screen:Number(BlendingMode.SCREEN),overlay:Number(BlendingMode.OVERLAY),
                difference:Number(BlendingMode.DIFFERENCE)}});
        })()'''))

    def snapshot(self):
        return json.loads(self.ae.run_jsx('''(function(){
            var c=app.project.itemByID(COMP),rows=[];
            for(var i=1;i<=c.numLayers;i++) {
                var l=c.layer(i);
                if(!(l instanceof AVLayer)) continue;
                rows.push({id:l.id,blend:Number(l.blendingMode),shy:l.shy,
                    preserveTransparency:l.preserveTransparency,
                    matte:l.trackMatteLayer?l.trackMatteLayer.id:null,
                    matteType:Number(l.trackMatteType),enabled:l.enabled});
            }
            return JSON.stringify(rows);
        })()'''.replace("COMP", str(self.ids["comp"]))))

    def write(self, changes, dry_run=False):
        return self.ae.set_native_layer_controls(
            changes, comp_id=self.ids["comp"], dry_run=dry_run)

    def test_all_modes_on_av_text_shape_preserve_mattes_and_single_undo(self):
        before = self.snapshot()
        for mode, expected in self.ids["modes"].items():
            with self.subTest(mode=mode):
                changes = [{"layer_id": self.ids[k], "blend_mode": mode,
                            "flags": {"shy": True}} for k in ("solid", "text", "shape")]
                dry = self.write(changes, dry_run=True)
                self.assertTrue(dry["ok"], dry)
                self.assertEqual(dry["validated"], 3)
                self.assertEqual(dry["written"], 0)
                self.assertEqual(dry["outcome"], "not_started")
                self.assertEqual(self.snapshot(), before)

                result = self.write(changes)
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["written"], 3)
                self.assertEqual(result["outcome"], "completed")
                target_ids = {row["layer_id"] for row in changes}
                wanted = [dict(row, blend=expected, shy=True)
                          if row["id"] in target_ids else row for row in before]
                self.assertEqual(self.snapshot(), wanted)
                self.ae.run_jsx('app.executeCommand(16); "undo"')
                self.assertEqual(self.snapshot(), before)

    def assert_rejected_without_writes(self, last, error):
        before = self.snapshot()
        changes = [{"layer_id": self.ids["solid"], "blend_mode": "screen",
                    "flags": {"shy": True}}, last]
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run, last=last):
                result = self.write(changes, dry_run=dry_run)
                self.assertFalse(result["ok"], result)
                self.assertIn(error, result["error"])
                self.assertEqual(result["outcome"], "not_started")
                self.assertTrue(result["retrySafe"])
                self.assertEqual(self.snapshot(), before)

    def test_later_camera_or_light_rejects_entire_batch(self):
        for kind in ("camera", "light"):
            self.assert_rejected_without_writes(
                {"layer_id": self.ids[kind], "blend_mode": "screen"},
                "blend_mode_not_supported")

    def test_later_restricted_flag_is_not_enabled_by_blend_support(self):
        for kind in ("text", "shape"):
            for flag in ("audio_active", "effects_active", "adjustment"):
                for value in (False, True):
                    self.assert_rejected_without_writes(
                        {"layer_id": self.ids[kind], "blend_mode": "screen",
                         "flags": {flag: value}}, "control_requires_av_layer")

    def test_later_locked_text_rejects_entire_batch(self):
        self.ae.run_jsx('''(function(){var c=app.project.itemByID(COMP);
            for(var i=1;i<=c.numLayers;i++) if(c.layer(i).id===LAYER) c.layer(i).locked=true;
            return "locked";})()'''.replace("COMP", str(self.ids["comp"]))
                       .replace("LAYER", str(self.ids["text"])))
        self.assert_rejected_without_writes(
            {"layer_id": self.ids["text"], "blend_mode": "screen"}, "layer_is_locked")


if __name__ == "__main__":
    unittest.main()
