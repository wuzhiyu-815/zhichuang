import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from flask import Flask
from agents.script.agent import 剧本智能体
from agents.script.story_editor import story_guidance


class StoryEditorTests(unittest.TestCase):
    def setUp(self):
        # Load just the route to avoid application startup and external services.
        tree = ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
        route = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name == 'api_story_chat')
        from flask import request, jsonify
        self.llm = Mock(return_value=(json.dumps({'reply': '已修改', 'story': '新正文'}), None))
        self.app = Flask(__name__)
        namespace = dict(app=self.app, request=request, jsonify=jsonify, json=json,
                         llm_chat=self.llm, parse_json_from_text=json.loads,
                         selected_stage_skill=lambda stage, skill_id=None: story_guidance() if skill_id != 'none' else '',
                         剧本智能体=剧本智能体)
        exec(compile(ast.Module(body=[route], type_ignores=[]), 'app.py', 'exec'), namespace)
        self.client = self.app.test_client()

    def test_route_uses_agent_skill_and_preserves_input_and_model(self):
        original = '她留下信。\n他没有回来。'
        response = self.client.post('/api/story/chat', json={
            'idea': original, 'message': '只改对白，保留悲剧', 'model': 'chosen-model',
            'history': [{'role': 'system', 'content': 'invalid'},
                        {'role': 'user', 'content': '保留人物'}],
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['story'], '新正文')
        messages = self.llm.call_args.args[0]
        self.assertIn(story_guidance(), messages[0]['content'])
        payload = json.loads(messages[1]['content'])
        self.assertEqual(payload['当前正文'], original)
        self.assertEqual(len(payload['此前对话']), 1)
        self.assertEqual(self.llm.call_args.kwargs['model'], 'chosen-model')

    def test_invalid_input_does_not_call_model(self):
        response = self.client.post('/api/story/chat', json={'idea': '', 'message': '改'})
        self.assertEqual(response.status_code, 400)
        self.llm.assert_not_called()

    def test_story_skill_can_be_disabled(self):
        response = self.client.post('/api/story/chat', json={
            'idea': '正文', 'message': '改', 'skill_id': 'none'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(story_guidance(), self.llm.call_args.args[0][0]['content'])

    def test_model_failure_and_invalid_story_keep_error_contract(self):
        for result in [(None, 'offline'), ('{"story": ""}', None)]:
            with self.subTest(result=result):
                self.llm.return_value = result
                response = self.client.post('/api/story/chat', json={'idea': '正文', 'message': '改'})
                self.assertEqual(response.status_code, 502)
                self.assertFalse(response.json['ok'])


if __name__ == '__main__':
    unittest.main()
