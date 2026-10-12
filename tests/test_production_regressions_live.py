"""Opt-in regression probes; never run against a populated or saved user project."""
import json
import os
from pathlib import Path
import unittest

from ae2claude_mcp.production import invoke
from ae2claude_mcp.runtime import bridge


@unittest.skipUnless(os.environ.get('AE2CLAUDE_PRODUCTION_LIVE_TEST') == '1', 'requires an empty AE and explicit live opt-in')
class ProductionRegressionLiveTests(unittest.TestCase):
    def test_regressions(self):
        root=Path(os.environ['AE2CLAUDE_PRODUCTION_TEST_DIR']).resolve()/'regressions'
        root.mkdir(parents=True,exist_ok=True)
        results=[]
        with bridge() as ae:
            def jsx(code):
                return json.loads(ae.run_jsx('(function(){'+code+'})()'))
            self.assertEqual(jsx('return JSON.stringify({n:app.project.numItems,file:!!app.project.file});'),{'n':0,'file':False})
            def call(action,opts,dry=False,ok=True):
                r=invoke(ae,action,opts,dry)
                results.append({'action':action,'options':opts,'result':r})
                self.assertEqual(r['ok'],ok,r)
                return r
            try:
                ids=jsx('''var a=app.project.items.addFolder('Parent'),b=app.project.items.addFolder('Child');b.parentFolder=a;
var c=app.project.items.addComp('Probe',320,180,1,1,25),t=c.layers.addText('ABC DEF'),s=c.layers.addShape();
s.property('ADBE Root Vectors Group').addProperty('ADBE Vector Group').name='First';
s.property('ADBE Root Vectors Group').addProperty('ADBE Vector Group').name='Second';
return JSON.stringify({a:a.id,b:b.id,c:c.id,t:t.id,s:s.id});''')
                r=call('project_items',{'changes':[{'item_id':ids['a'],'folder_id':ids['b']},{'item_id':ids['b'],'folder_id':0}]})
                self.assertEqual([x['parentId'] for x in r['result']],[ids['b'],0])
                # Object-prototype names must remain valid AE names.
                call('project_items',{'changes':[{'item_id':ids['c'],'name':'toString'}]})
                r=call('shape_contents',{'comp_id':ids['c'],'layer':ids['s'],'max_nodes':2})
                self.assertTrue(r['truncated'])
                self.assertEqual(r['result'][1]['name'],'First')
                text={'comp_id':ids['c'],'layer':ids['t'],'start':4,'end':7,'text':'X\r\nY\nZ😀'}
                r=call('text_range',text)
                self.assertEqual(r['result']['text'],'ABC X\rY\rZ😀')
                call('expose_control',{'comp_id':ids['c'],'layer':ids['t'],'path':['ADBE Transform Group','ADBE Opacity'],'name':'Opacity'})
                outer=jsx('var c=app.project.items.addComp("Outer",320,180,1,1,25),l=c.layers.add(app.project.itemByID('+str(ids['c'])+'));return JSON.stringify({c:c.id,l:l.id});')
                ep={'comp_id':outer['c'],'layer':outer['l'],'path':[0]}
                call('essential_property',{**ep,'time':0,'value':0})
                r=call('essential_property',{**ep,'time':0.5,'value':100})
                self.assertEqual(r['result']['value'],100)
                self.assertEqual(r['result']['time'],0.5)
                ae.run_jsx('app.project.save(new File('+json.dumps(str(root/'fixture.aep'))+'));')
                first=call('render_output',{'comp_id':ids['c']})['result']
                second=call('render_output',{'comp_id':ids['c']})['result']
                self.assertNotEqual(first['path'],second['path'])
                r=call('render_output',{'comp_id':ids['c'],'output_path':first['path'],'overwrite':True},ok=False)
                self.assertIn('render_output_reserved',r['error'])
                before=jsx('return JSON.stringify(app.project.renderQueue.numItems);')
                frames=root/'frame_00001.png';frames.write_bytes(b'preserve-existing-frame')
                r=call('render_output',{'comp_id':ids['c'],'output_path':str(root/'frame_[#####].png')},dry=True,ok=False)
                self.assertIn('render_destination_exists',r['error'])
                self.assertEqual(frames.read_bytes(),b'preserve-existing-frame')
                # Disk conflict must use the extension chosen by the actual output module.
                Path(first['path']).write_bytes(b'preserve-existing-output')
                ae.run_jsx('app.project.renderQueue.item(1).remove();')
                third=call('render_output',{'comp_id':ids['c']})['result']
                self.assertNotIn(third['path'],[first['path'],second['path']])
                self.assertEqual(Path(first['path']).read_bytes(),b'preserve-existing-output')
                self.assertEqual(jsx('return JSON.stringify(app.project.renderQueue.numItems);'),before)
            finally:
                ae.run_jsx('app.project.close(CloseOptions.DO_NOT_SAVE_CHANGES);app.newProject();')
                (root/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
