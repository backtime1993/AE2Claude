import json
import os
import unittest

from ae_bridge import AEBridge


@unittest.skipUnless(os.environ.get('AE2CLAUDE_LIVE_TEST') == '1', 'requires a running AE acceptance instance')
class NativePositionAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.ae=AEBridge()

        state=json.loads(self.ae.run_jsx('JSON.stringify({items:app.project.numItems,file:app.project.file?app.project.file.fsName:null})'))
        if state['items'] or state['file']:
            self.ae.close()
            self.skipTest('requires an empty unsaved acceptance project')
        self.ids=json.loads(self.ae.run_jsx('''(function(){
            var c=app.project.items.addComp("native position acceptance",320,180,1,10,24000/1001);
            var a=c.layers.addNull();var b=c.layers.addNull();b.threeDLayer=true;
            return JSON.stringify({comp:c.id,two:a.id,three:b.id});
        })()'''))

    def tearDown(self):
        self.ae.run_jsx('app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);app.newProject(); "clean"')
        self.ae.close()

    def write(self, layer, value, dry_run=False):
        return self.ae.set_native_keyframes(self.ids[layer], ['ADBE Transform Group','ADBE Position'],
            [{'time':0,'value':value},{'time':1001/24000,'value':value}],
            comp_id=self.ids['comp'],dry_run=dry_run)

    def keys(self, layer):
        return self.ae.get_native_keyframes(self.ids[layer],['ADBE Transform Group','ADBE Position'],comp_id=self.ids['comp'])

    def test_two_dimensional_position_accepts_xy_and_preserves_native_read_contract(self):
        result=self.write('two',[10,20])
        self.assertTrue(result['ok'],result)
        keys=self.keys('two')['keyframes']
        self.assertEqual([k['value'] for k in keys],[[10,20,0],[10,20,0]])
        self.ae.run_jsx('app.executeCommand(16); "undo"')
        self.assertEqual(self.keys('two')['total'],0)

    def test_dry_run_normalizes_but_does_not_write(self):
        result=self.write('two',[10,20],True)
        self.assertTrue(result['ok'],result)
        self.assertEqual(self.keys('two')['total'],0)

    def test_three_dimensional_mismatch_is_not_started_and_leaves_keys_unchanged(self):
        self.assertTrue(self.write('three',[10,20,30])['ok'])
        before=self.keys('three')
        result=self.write('three',[50,60])
        self.assertFalse(result['ok'],result)
        self.assertEqual(result['outcome'],'not_started')
        self.assertTrue(result['retrySafe'])
        self.assertEqual(self.keys('three'),before)

    def test_scalar_position_input_is_rejected_before_mutation(self):
        result=self.write('two',50)
        self.assertFalse(result['ok'],result)
        self.assertEqual(result['outcome'],'not_started')
        self.assertEqual(self.keys('two')['total'],0)
