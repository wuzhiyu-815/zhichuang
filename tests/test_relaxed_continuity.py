import copy
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from infrastructure.agent_continuity import (
    LEGACY_RULES, plan_script, previous_video, render_references, source_signature,
)
from infrastructure.dependency_scheduler import render_groups, resolve_selection, run
from infrastructure.shot_continuity import (
    apply_continuity_intro, requires_previous_frame, validate_continuity,
)


def shots():
    result = []
    for i, mode in enumerate(('none', 'state', 'frame', 'state'), 1):
        start = copy.deepcopy(result[-1]['continuity']['end']) if result else {
            'location': '门边', 'characters': '甲站定，右手持刀', 'props': '刀已出鞘'}
        result.append({'index': i, 'action': f'动作{i}', 'dialogue': [], 'continuity': {
            'transition': 'opening' if i == 1 else 'continuous',
            'handoff_mode': mode, 'previous_index': i-1 if i > 1 else None,
            'reason': '已站定可独立起拍' if mode != 'frame' else '腾空接触动作跨镜未结束',
            'camera_mode': 'changed', 'start': start,
            'end': {'location': f'位置{i}', 'characters': f'姿态{i}', 'props': '右手持刀'},
        }})
    return result


class RelaxedContinuityTests(unittest.TestCase):
    def test_missing_opening_characters_is_repaired_with_previous_response(self):
        good = {'action': '甲推门进入', 'transition': 'opening', 'reason': '首镜',
                'camera_mode': 'changed', 'handoff_mode': 'none',
                'start_location': '门外', 'start_characters': '甲站在门外，双手自然下垂',
                'start_props': '门关闭', 'end_location': '门内',
                'end_characters': '甲站在门内，右手扶门', 'end_props': '门打开'}
        bad = dict(good)
        bad.pop('start_characters')
        bad_text = json.dumps(bad, ensure_ascii=False)
        engine = SimpleNamespace(llm_chat=Mock(side_effect=[
            (bad_text, None), (json.dumps(good), None)]), parse_json_from_text=json.loads)
        script = {'shots': [{'index': 1, 'action': '甲推门进入', 'dialogue': []}]}
        result = plan_script(engine, script)
        self.assertEqual(validate_continuity(result['shots']), [])
        self.assertEqual(result['shots'][0]['continuity']['start']['characters'], good['start_characters'])
        self.assertNotIn('continuity', script['shots'][0])
        first = engine.llm_chat.call_args_list[0].args[0]
        retry = engine.llm_chat.call_args_list[1].args[0]
        self.assertIn('11个扁平字符串字段', first[1]['content'])
        self.assertEqual(retry[-2], {'role': 'assistant', 'content': bad_text})
        self.assertIn('start_characters', retry[-1]['content'])

    def test_missing_opening_state_still_fails_after_retry(self):
        engine = SimpleNamespace(llm_chat=Mock(return_value=('{}', None)),
                                 parse_json_from_text=json.loads)
        script = {'shots': [{'index': 1, 'action': '开场'}]}
        with self.assertRaisesRegex(ValueError, '镜头交接规划失败'):
            plan_script(engine, script)
        self.assertEqual(engine.llm_chat.call_count, 2)
        self.assertNotIn('continuity', script['shots'][0])

    def test_parallel_state_shots_and_ordered_frame_successor(self):
        sequence = []
        lock = threading.Lock()
        barrier = threading.Barrier(2)
        def worker(index):
            if index in (1, 2):
                barrier.wait(timeout=3)  # Fails if state continuation still waits on shot 1.
            if index == 3:
                with lock:
                    self.assertIn(2, sequence)
            return index
        def completed(index, result):
            with lock:
                sequence.append(index)
        external = Mock(side_effect=AssertionError('unexpected external dependency'))
        self.assertEqual(run(shots(), [1, 2, 3, 4], worker, completed, external, workers=2), {1, 2, 3, 4})
        self.assertEqual([g['indexes'] for g in render_groups(shots())], [[1], [2, 3], [4]])

    def test_failed_frame_parent_blocks_only_its_dependents(self):
        seen = []
        def worker(index):
            seen.append(index)
            if index == 2:
                raise ValueError('failed')
        with self.assertRaisesRegex(ValueError, '第3镜'):
            run(shots(), [1, 2, 3, 4], worker, lambda *args: None, lambda s: None)
        self.assertEqual(set(seen), {1, 2, 4})

    def test_selection_stops_at_text_handoff(self):
        external = Mock(side_effect=ValueError('missing video'))
        self.assertEqual(resolve_selection(shots(), [3], external), [2, 3])
        external.reset_mock()
        self.assertEqual(resolve_selection(shots(), [4], external), [4])
        external.assert_not_called()

    def test_state_handoff_needs_no_video_or_reference_slot(self):
        shot = shots()[1]
        self.assertIsNone(previous_video(None, {}, shot))
        refs = [f'ref{i}' for i in range(9)]
        prompt, actual_refs, handoff = render_references(None, {}, shot, '原提示词', refs)
        self.assertEqual(actual_refs, refs)
        self.assertIsNone(handoff)
        self.assertIn('接上一镜头', prompt)
        with self.assertRaises(ValueError):
            previous_video(None, {}, shots()[2])

    def test_legacy_dependencies_remain_strict_until_reviewed(self):
        shot = shots()[1]
        shot['continuity'].pop('handoff_mode')
        self.assertTrue(requires_previous_frame(shot))

    def test_validation_keeps_state_continuity(self):
        script_shots = shots()
        self.assertEqual(validate_continuity(script_shots), [])
        script_shots[1]['continuity']['start']['characters'] = '错误重置'
        self.assertTrue(validate_continuity(script_shots))

    def test_prompt_prefix_is_idempotent_and_preserves_dialogue(self):
        raw = 'integrated_multimodal_description:\n<Picture 1>角色\n[Shot 1]\n<Subject 1> (S1) says:\n<d>[Chinese]别动！</d>\noverall_soundscape:风声\nnon_diegetic_music:无'
        shot = shots()[1]
        result = apply_continuity_intro(shot, raw)
        self.assertEqual(result, apply_continuity_intro(shot, result))
        self.assertTrue(result.startswith('integrated_multimodal_description:\n【接镜说明'))
        self.assertIn('开场位置：位置1', result)
        self.assertTrue(result.endswith(raw.split('\n', 1)[1]))
        self.assertEqual(apply_continuity_intro(shots()[0], raw), raw)

    def test_cut_intro_uses_current_location(self):
        shot = shots()[1]
        shot['continuity'].update(transition='cut', handoff_mode='none')
        shot['continuity']['start']['location'] = '次日屋顶'
        result = apply_continuity_intro(shot, '镜头内容')
        self.assertIn('接上一镜头剧情', result)
        self.assertIn('次日屋顶', result)

    def test_cached_tail_reference_is_removed_for_parallel_shot(self):
        raw = ('正文<Picture 1>\n实际衔接参考（不朗读）：<Picture 9>为上一镜实际末帧，只约束空间、起始姿态、持物和动作进度；'
               '角色身份、衣着、道具外观仍由原有参考图锁定。保持末帧机位和初始构图。\n[Shot 1]动作')
        result = apply_continuity_intro(shots()[1], raw)
        self.assertNotIn('<Picture 9>', result)
        self.assertIn('<Picture 1>', result)
        self.assertIn('[Shot 1]动作', result)

    def test_legacy_upgrade_preserves_actions_and_boundary_states(self):
        original = {'shots': shots()}
        for s in original['shots']:
            s['continuity'].pop('handoff_mode')
        snapshot = copy.deepcopy(original)
        answers = [json.dumps({'handoff_mode': m, 'reason': '复核依据'}) for m in ('state', 'frame', 'state')]
        engine = SimpleNamespace(llm_chat=Mock(side_effect=[(a, None) for a in answers]), parse_json_from_text=json.loads)
        upgraded = plan_script(engine, original, source_signature(original, LEGACY_RULES))
        self.assertEqual(original, snapshot)
        self.assertEqual(validate_continuity(upgraded['shots']), [])
        self.assertEqual([s['continuity']['handoff_mode'] for s in upgraded['shots']], ['none','state','frame','state'])
        for before, after in zip(original['shots'], upgraded['shots']):
            self.assertEqual(before['action'], after['action'])
            self.assertEqual(before['continuity']['start'], after['continuity']['start'])
            self.assertEqual(before['continuity']['end'], after['continuity']['end'])
        engine.llm_chat.reset_mock()
        self.assertIs(plan_script(engine, upgraded, source_signature(upgraded)), upgraded)
        engine.llm_chat.assert_not_called()


if __name__ == '__main__':
    unittest.main()
