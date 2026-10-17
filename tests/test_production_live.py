"""Opt-in authoring acceptance. Requires an EMPTY unsaved AE project."""
import json
import os
from pathlib import Path
import time
import unittest

from ae2claude_mcp.runtime import bridge
from ae2claude_mcp.production import invoke


@unittest.skipUnless(os.environ.get('AE2CLAUDE_PRODUCTION_LIVE_TEST') == '1', 'requires empty AE project and explicit live opt-in')
class ProductionLiveTests(unittest.TestCase):
    def test_authoring_roundtrip(self):
        root=Path(os.environ['AE2CLAUDE_PRODUCTION_TEST_DIR']).resolve()
        root.mkdir(parents=True,exist_ok=True)
        evidence=[]
        with bridge() as ae:
            def jsx(code):
                return json.loads(ae.run_jsx('(function(){'+code+'})()'))
            before=jsx('return JSON.stringify({items:app.project.numItems,file:app.project.file?app.project.file.fsName:null,dirty:app.project.dirty});')
            self.assertEqual(before['items'],0,'Never run fixture against a user project')
            self.assertIsNone(before['file'])
            ids=jsx('''var c=app.project.items.addComp('PV_CAPABILITY_TEST',320,180,1,0.4,25);
var t=c.layers.addText('ABC DEF');t.name='Label';var p=t.property('ADBE Text Properties').property('ADBE Text Document'),d=p.value;
d.fontSize=28;d.characterRange(0,3).fillColor=[1,0,0];d.characterRange(4,7).fillColor=[0,1,0];p.setValue(d);
t.property('ADBE Transform Group').property('ADBE Position').setValue([30,95]);
var s=c.layers.addShape();s.name='Shape';
var opacity=t.property('ADBE Transform Group').property('ADBE Opacity');opacity.setValueAtTime(0,30);opacity.setValueAtTime(0.2,100);
return JSON.stringify({comp:c.id,text:t.id,shape:s.id});''')
            def call(action, options=None, dry=False):
                o={'comp_id':ids['comp'],**(options or {})}
                result=invoke(ae,action,o,dry)
                evidence.append({'action':action,'options':o,'response':result})
                (root/'live-results.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
                self.assertTrue(result.get('ok'),result)
                return result
            try:
                call('template_settings',{'name':'PV Capability Test'})
                call('expose_control',{'layer':ids['text'],'path':['ADBE Text Properties','ADBE Text Document'],'name':'Title'})
                eg=call('essential_graphics')['result']
                self.assertEqual(len(eg['controllers']),1)
                call('rename_control',{'index':eg['controllers'][0]['index'],'name':'Headline'})
                outer=jsx("var c=app.project.itemByID("+str(ids['comp'])+");var outer=app.project.items.addComp('PV_OUTER',320,180,1,0.4,25);var l=outer.layers.add(c);return JSON.stringify({comp:outer.id,layer:l.id});")
                ep=call('essential_properties',{'comp_id':outer['comp'],'layer':outer['layer']})['result']
                self.assertTrue(len(ep)>1)
                # Test a scalar Essential Property independently from Source Text.
                call('expose_control',{'layer':ids['shape'],'path':['ADBE Transform Group','ADBE Opacity'],'name':'Shape opacity'})
                ep=call('essential_properties',{'comp_id':outer['comp'],'layer':outer['layer']})['result']
                scalar=next(x for x in ep if x['name']=='Shape opacity')
                call('essential_property',{'comp_id':outer['comp'],'layer':outer['layer'],'path':scalar['path'],'value':65})
                group=call('shape_operator',{'layer':ids['shape'],'path':[],'operation':'add','match_name':'ADBE Vector Group','name':'Badge'})['result']['path']
                contents=group+['ADBE Vectors Group']
                call('shape_operator',{'layer':ids['shape'],'path':contents,'operation':'add','match_name':'ADBE Vector Shape - Rect'})
                stroke=call('shape_operator',{'layer':ids['shape'],'path':contents,'operation':'add','match_name':'ADBE Vector Graphic - Stroke'})['result']['path']
                call('stroke_dashes',{'layer':ids['shape'],'path':stroke,'dashes':[12,6,3,6],'offset':2})
                trim=call('shape_operator',{'layer':ids['shape'],'path':contents,'operation':'add','match_name':'ADBE Vector Filter - Trim'})['result']['path']
                call('shape_operator',{'layer':ids['shape'],'path':trim,'operation':'rename','name':'Trim test'})
                call('shape_operator',{'layer':ids['shape'],'path':trim,'operation':'enable','enabled':False})
                call('shape_operator',{'layer':ids['shape'],'path':trim,'operation':'remove'})
                self.assertTrue(call('shape_contents',{'layer':ids['shape']})['result'])
                plan=call('text_range',{'layer':ids['text'],'start':4,'end':7,'text':'XYZ'},True)
                self.assertFalse(plan['applied'])
                call('text_range',{'layer':ids['text'],'start':4,'end':7,'text':'XYZ'})
                styles=jsx("var d=app.project.itemByID("+str(ids['comp'])+").layer('Label').property('ADBE Text Properties').property('ADBE Text Document').value;return JSON.stringify({text:d.text,left:d.characterRange(0,3).fillColor,right:d.characterRange(4,7).fillColor});")
                self.assertEqual(styles,{'text':'ABC XYZ','left':[1,0,0],'right':[0,1,0]})
                for mode in ('linear','hold','bezier'):
                    call('keyframe_interpolation',{'layer':ids['text'],'path':['ADBE Transform Group','ADBE Opacity'],'key_indices':[0,1],'in_type':mode})
                folder=call('create_folder',{'name':'Test organization'})['result']['id']
                call('project_items',{'changes':[{'item_id':ids['comp'],'name':'PV_RENAMED','folder_id':folder}]})
                self.assertEqual(call('create_folder',{'name':'Test organization'})['result']['created'],False)
                # Save only the isolated fixture, then export to a unique test folder.
                ae.run_jsx('app.project.save(new File('+json.dumps(str(root/'fixture.aep'))+'));')
                mogrt=call('export_mogrt',{'output_dir':str(root)})['result']
                self.assertGreater(Path(mogrt['path']).stat().st_size,0)
                queued=call('render_output',{'output_path':str(root/'preview.mov')})['result']
                self.assertEqual(ae.start_render(),'render_started')
                deadline=time.monotonic()+60
                while time.monotonic()<deadline:
                    state=jsx('return JSON.stringify({rendering:app.project.renderQueue.rendering,status:app.project.renderQueue.item(1).status,done:RQItemStatus.DONE});')
                    if not state['rendering'] and state['status']==state['done']:
                        break
                    time.sleep(0.5)
                else:
                    self.fail('fixture render did not complete')
                self.assertGreater(Path(queued['path']).stat().st_size,0)
                evidence.append({'verifiedStyles':styles,'render':state,'output':queued['path']})
            finally:
                # This fixture exclusively owns the initially empty project. Never reopen a user AEP.
                ae.run_jsx('app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);app.newProject();')
                evidence.append({'cleanup':jsx('return JSON.stringify({items:app.project.numItems,file:app.project.file?app.project.file.fsName:null});')})
                (root/'live-results.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
