import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from infrastructure.agent_continuity import plan_script


class StartRepairTests(unittest.TestCase):
    def test_targeted_repair_preserves_existing_fields(self):
        plan = dict(action='甲推门', transition='opening', reason='首镜',
                    camera_mode='changed', handoff_mode='none',
                    start_characters='甲站门外', start_props='门关闭',
                    end_location='门内', end_characters='甲站门内', end_props='门打开')
        patch = dict(start_location='门外', start_characters='不应替换', start_props='不应替换')
        engine = SimpleNamespace(llm_chat=Mock(side_effect=[
            (json.dumps(plan), None), (json.dumps(plan), None), (json.dumps(patch), None)]),
            parse_json_from_text=json.loads)
        script = {'shots': [{'index': 1, 'action': '甲推门'}]}
        result = plan_script(engine, script)
        start = result['shots'][0]['continuity']['start']
        self.assertEqual(start, dict(location='门外', characters='甲站门外', props='门关闭'))
        self.assertNotIn('continuity', script['shots'][0])

    def test_failed_targeted_repair_does_not_fabricate_state(self):
        plan = dict(action='甲推门', transition='cut', reason='换场',
                    camera_mode='changed', handoff_mode='none',
                    end_location='门内', end_characters='甲站门内', end_props='门打开')
        engine = SimpleNamespace(llm_chat=Mock(side_effect=[
            (json.dumps(plan), None), (json.dumps(plan), None), ('{}', None)]),
            parse_json_from_text=json.loads)
        with self.assertRaisesRegex(ValueError, 'start_location'):
            plan_script(engine, {'shots': [{'index': 1, 'action': '甲推门'}]})
