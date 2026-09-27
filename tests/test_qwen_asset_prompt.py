import ast
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from infrastructure.qwen_image import reference_prompt


class AssetPromptTests(unittest.TestCase):
    def setUp(self):
        tree = ast.parse(Path('app.py').read_text(encoding='utf-8-sig'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'gen_asset_image')
        self.llm = Mock(return_value=('规范后的提示词', None))
        self.image = Mock(return_value=('image.png', None))
        self.ns = dict(json=json, runtime_config=lambda: {}, selected_stage_skill=lambda stage: 'rules',
                       llm_chat=self.llm, gen_image=self.image, lock_prompt=lambda p, s: p,
                       ensure_race_desc=lambda s: s, sanitize_scene_text=lambda s, names: s,
                       character_reference_is_landscape=lambda path: True, SCENE_REFERENCE_RULE='空场景约束')
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'app.py', 'exec'), self.ns)

    def test_all_types_provide_explicit_context(self):
        for kind in ('char', 'scene', 'prop'):
            with self.subTest(kind=kind):
                self.ns['gen_asset_image'](kind, '测试主体', '已锁定描述', '水彩')
                context = json.loads(self.llm.call_args.args[0][1]['content'])
                self.assertEqual(context['资产类型'], kind)
                self.assertEqual(context['画风'], '水彩')
                self.assertFalse(context['有参考图'])

    def test_manual_prompt_is_not_rewritten(self):
        self.ns['gen_asset_image']('prop', '杯', '陶杯', '水彩', prompt='手工确认的完整提示词')
        self.llm.assert_not_called()
        self.assertEqual(self.image.call_args.args[0], '手工确认的完整提示词')

    def test_refinement_failure_does_not_submit_image(self):
        self.llm.return_value = (None, 'offline')
        path, prompt, error = self.ns['gen_asset_image']('scene', '庭院', '石路', '水彩')
        self.assertIsNone(path)
        self.assertEqual(error, 'offline')
        self.image.assert_not_called()

    def test_reference_rules_do_not_mix_asset_types(self):
        for kind in ('scene', 'prop'):
            prompt = reference_prompt(kind, '主体', '描述', '用户修改')
            self.assertNotIn('第一栏', prompt)
            self.assertIn('用户修改', prompt)
        self.assertIn('头顶至腰部', reference_prompt('char', '角色', '描述', '用户修改'))


if __name__ == '__main__':
    unittest.main()
