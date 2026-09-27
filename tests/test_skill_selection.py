import ast
import unittest
from pathlib import Path
from unittest.mock import Mock


class SkillSelectionTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
        names = {'selected_stage_skill', '_阶段技能'}
        nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        self.cfg = {'story_skill_id': 'custom:story.md'}
        self.ns = {
            'runtime_config': lambda: self.cfg,
            'skills_catalog': lambda: [
                {'id': 'custom:story.md', 'stages': ['story']},
                {'id': 'custom:asset.md', 'stages': ['asset']},
                {'id': 'builtin:qwen21-asset', 'stages': ['asset']},
                {'id': 'builtin:story-writing', 'stages': ['story', 'script']},
            ],
            '_技能内容': Mock(side_effect=lambda sid: 'rules:' + sid),
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'app.py', 'exec'), self.ns)
        self.select = self.ns['selected_stage_skill']

    def test_default_explicit_and_disabled_selection(self):
        self.assertEqual(self.select('story'), 'rules:custom:story.md')
        self.assertEqual(self.select('story', 'auto'), 'rules:builtin:story-writing')
        self.assertEqual(self.select('story', 'none'), '')
        self.assertEqual(self.select('asset', 'auto'), 'rules:builtin:qwen21-asset')

    def test_wrong_stage_and_deleted_skill_are_not_loaded(self):
        self.assertEqual(self.select('asset', 'custom:story.md'), '')
        self.assertEqual(self.select('story', 'custom:deleted.md'), '')
        self.ns['_技能内容'].assert_not_called()

    def test_project_selection_overrides_global(self):
        self.assertEqual(self.select('asset', config={'asset_skill_id': 'custom:asset.md'}),
                         'rules:custom:asset.md')
        self.assertEqual(self.select('story', config={'story_skill_id': 'none'}), '')


if __name__ == '__main__':
    unittest.main()
