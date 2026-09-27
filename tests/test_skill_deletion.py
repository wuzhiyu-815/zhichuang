import ast
import copy
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

from flask import Flask, jsonify, request


class SkillDeletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.custom = self.root / 'custom'
        self.custom.mkdir()
        self.builtin = self.root / 'builtin.md'
        self.builtin.write_text('BUILTIN RULES', encoding='utf-8')
        (self.custom / 'user.md').write_text('USER RULES', encoding='utf-8')
        self.admin = Mock(is_admin=Mock(return_value=True))
        self.app = Flask(__name__)
        definitions = {sid: {'id': sid, 'path': str(self.builtin), 'name': sid,
                            'stages': ['story', 'video_prompt'], 'builtin': True}
                       for sid in ['builtin:story-writing', 'builtin:minimax-dialogue',
                                   'builtin:minimax-action', 'builtin:anime-action']}
        self.config = {}
        self.ns = dict(app=self.app, request=request, jsonify=jsonify, json=json, copy=copy,
                       os=os, time=time, re=re, MULTIUSER=self.admin, CONFIG=self.config,
                       CONFIG_IO_LOCK=threading.RLock(), save_config=Mock(),
                       CUSTOM_SKILLS_DIR=str(self.custom), SKILLS_INDEX_PATH=str(self.custom / 'index.json'),
                       内置技能定义=definitions, DIALOGUE_SKILL_PATH=str(self.builtin),
                       ACTION_SKILL_PATH=str(self.builtin), COMBAT_SKILL_PATH=str(self.builtin),
                       runtime_config=lambda: self.config, 读取自定义技能=lambda mode: '')
        names = {'_读取技能索引', '_保存技能索引', '_技能已删除', '_技能内容', 'skills_catalog',
                 '_阶段技能', 'selected_stage_skill', 'api_skill_detail', '读取文戏技能',
                 '读取武戏技能', '读取二次元打戏技能', '获取提示词技能模式', '是否文戏场景', '是否打戏场景'}
        tree = ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), self.ns)
        self.client = self.app.test_client()

    def delete(self, sid):
        return self.client.delete('/api/skills/' + sid)

    def test_admin_delete_persists_without_touching_source(self):
        self.assertTrue(self.client.get('/api/skills/builtin:story-writing').json['skill']['can_delete'])
        response = self.delete('builtin:story-writing')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('builtin:story-writing', [s['id'] for s in response.json['skills']])
        self.assertEqual(self.builtin.read_text(), 'BUILTIN RULES')
        record = json.loads((self.custom / 'index.json').read_text())
        self.assertIn('builtin:story-writing', record['__deleted_builtins__'])
        self.assertEqual(self.client.get('/api/skills/builtin:story-writing').status_code, 404)
        self.assertEqual(self.ns['selected_stage_skill']('story', 'auto'), '')
        self.assertEqual(self.ns['selected_stage_skill']('story', 'builtin:story-writing'), '')
        self.assertEqual(self.ns['_技能内容']('builtin:story-writing'), '')
        # Restoring/updating source files must not reactivate this deployment's deletion.
        self.builtin.write_text('NEW UPSTREAM RULES')
        self.assertNotIn('builtin:story-writing', [s['id'] for s in self.ns['skills_catalog']()])

    def test_members_and_single_user_cannot_delete_builtins(self):
        self.admin.is_admin.return_value = False
        self.assertFalse(self.client.get('/api/skills/builtin:story-writing').json['skill']['can_delete'])
        self.assertEqual(self.delete('builtin:story-writing').status_code, 403)
        self.assertEqual(self.delete('custom:user.md').status_code, 403)
        self.ns['MULTIUSER'] = None
        self.assertEqual(self.delete('builtin:story-writing').status_code, 403)
        self.assertEqual(self.delete('custom:user.md').status_code, 200)

    def test_content_stays_readonly_and_custom_delete_preserves_tombstones(self):
        self.assertEqual(self.client.put('/api/skills/builtin:story-writing', json={'content':'changed'}).status_code, 403)
        self.delete('builtin:story-writing')
        self.assertEqual(self.delete('custom:user.md').status_code, 200)
        self.assertFalse((self.custom / 'user.md').exists())
        self.assertTrue(self.ns['_技能已删除']('builtin:story-writing'))

    def test_video_legacy_auto_and_explicit_paths_respect_deletion(self):
        cases = [('builtin:minimax-dialogue', 'dialogue', '对话', '读取文戏技能'),
                 ('builtin:minimax-action', 'action', '战斗', '读取武戏技能'),
                 ('builtin:anime-action', 'anime_action', '动漫战斗', '读取二次元打戏技能')]
        for sid, legacy, text, reader in cases:
            with self.subTest(sid=sid):
                self.assertEqual(self.delete(sid).status_code, 200)
                self.config.clear()
                self.config['video_skill_id'] = sid
                self.assertEqual(self.ns['获取提示词技能模式'](text), 'none')
                self.config.clear()
                self.config['prompt_skill_mode'] = legacy
                self.assertEqual(self.ns['获取提示词技能模式'](text), 'none')
                self.config.clear()
                self.assertEqual(self.ns['获取提示词技能模式'](text), 'none')
                self.assertEqual(self.ns[reader](), '')


if __name__ == '__main__':
    unittest.main()
