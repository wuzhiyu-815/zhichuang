import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agents.assets.agent import 资产智能体实例
from core.skill_result import 技能结果


class AssetProgressTests(unittest.TestCase):
    def test_saved_image_is_reported_before_next_generation_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scene.png'
            path.write_bytes(b'image')
            project = {'id': 'test', 'script': {'scenes': [
                {'name': 'first'}, {'name': 'second'}]}}
            saved = []
            events = []
            app = SimpleNamespace(load_project=lambda _: project,
                                  save_project=lambda p: saved.append(copy.deepcopy(p)))
            agent = 资产智能体实例()
            agent.记录决策 = Mock()

            def skill(_registry, _project, name, params):
                if name == '检查资产文件':
                    return 技能结果(True, 数据={'通过': True})
                if params['name'] == 'second':
                    self.assertEqual(len(events), 1)
                    return 技能结果(False, 错误='second failed')
                return 技能结果(True, 数据={'path': str(path), 'prompt': 'first prompt'})

            agent.调用技能 = skill

            def progress(asset, done, total):
                self.assertEqual(saved[-1]['assets'][asset['key']]['path'], asset['path'])
                events.append((asset, done, total))

            with patch.dict(sys.modules, {'app': app}):
                result = agent.执行(project, None, {'progress_callback': progress})
            self.assertFalse(result.成功)
            self.assertEqual(events[0][1:], (1, 2))
            self.assertEqual(events[0][0]['name'], 'first')


if __name__ == '__main__':
    unittest.main()
