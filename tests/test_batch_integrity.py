import unittest
from unittest.mock import Mock
from ae_bridge import AEBridge, JSXExecutionError
from ae2claude_mcp.properties import normalize_layer_ref, normalize_operations, property_batch


class BatchInputIntegrityTests(unittest.TestCase):
    def test_selector_accepts_integer_strings_but_rejects_coercion(self):
        self.assertEqual(normalize_layer_ref({'id':'17'}),{'id':17})
        for value in (True,False,1.0,1.5,None,[],{},'1.5','-1'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                normalize_layer_ref({'index':value})

    def test_nonfinite_values_times_and_textual_booleans_are_rejected(self):
        for field,value in [('value',float('nan')),('value',[1,float('inf')]),('time',float('nan')),
                            ('time',float('inf')),('time',True),('preExpression','false')]:
            operation={'action':'set','path':['ADBE Transform Group','ADBE Opacity'],'value':30}
            operation[field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                normalize_operations([operation])

    def test_unknown_native_outcome_is_never_replayed_through_jsx(self):
        for exc in [RuntimeError('agent_stream_batch failed after mutation'),
                    TimeoutError('agent_stream_batch timed out'),
                    RuntimeError("AttributeError: object 'layer' has no attribute 'agent_stream_batch'"),
                    JSXExecutionError({'ok':False,'error':'agent_stream_batch failed','outcome':'unknown','retrySafe':False})]:
            ae=AEBridge.__new__(AEBridge)
            ae.timeout=30
            ae._run_py=Mock(side_effect=exc)
            ae.run_jsx=Mock(return_value='{"ok":true}')
            with self.subTest(error=exc),self.assertRaises(type(exc)):
                property_batch(ae,1,[{'action':'set','path':['ADBE Transform Group','ADBE Opacity'],'value':12}])
            ae.run_jsx.assert_not_called()
