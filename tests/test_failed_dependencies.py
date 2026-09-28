import unittest
from unittest.mock import Mock, patch
from ae2claude_mcp.agent_runtime import execute_batch, resolve_references


class FailedDependencyTests(unittest.TestCase):
    def test_failed_dependencies_are_skipped_but_independent_steps_continue(self):
        for failure in [RuntimeError('unavailable'), {'ok': False, 'error': 'unavailable'}]:
            with self.subTest(failure=failure):
                bridge = Mock()
                if isinstance(failure, Exception):
                    bridge.project_info.side_effect = failure
                else:
                    bridge.project_info.return_value = failure
                bridge.get_layer_info.return_value = {'name': 'independent'}
                with patch('ae2claude_mcp.agent_runtime.bridge') as connection:
                    connection.return_value.__enter__.return_value = bridge
                    result = execute_batch([
                        {'method': 'project_info'},
                        {'method': 'get_layer_info', 'args': ['$0']},
                        {'method': 'get_layer_info', 'kwargs': {'name': '$1.name'}},
                        {'method': 'get_layer_info', 'args': ['independent']}], fail_fast=False)
                self.assertFalse(result['ok'])
                self.assertEqual([r['ok'] for r in result['results']], [False, False, False, True])
                self.assertIn('failed operation', result['results'][1]['error'])
                self.assertIn('failed operation', result['results'][2]['error'])
                bridge.get_layer_info.assert_called_once_with('independent')

    def test_successful_none_is_a_valid_result(self):
        self.assertIsNone(resolve_references('$0', [None]))

    def test_successful_null_field_is_a_valid_reference(self):
        self.assertEqual(resolve_references({'x': ['$0.value']}, [{'value': None}]), {'x': [None]})
