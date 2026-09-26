"""Reference changes are staged for human review before replacing shot descriptions."""
import copy
import hashlib
import json
import uuid
from functools import wraps
from flask import request, jsonify

REFERENCE_EDIT_WAITS = set()


def reference_edit_wait(func):
    """Only expose editing while the pipeline is paused for human input."""
    @wraps(func)
    def waiting(pid, *args, **kwargs):
        REFERENCE_EDIT_WAITS.add(pid)
        try:
            return func(pid, *args, **kwargs)
        finally:
            REFERENCE_EDIT_WAITS.discard(pid)
    return waiting


def affected(project, key):
    kind, name = key.split('_', 1)
    return [s for s in (project.get('script') or {}).get('shots', []) if
            (kind == 'char' and (name in s.get('characters', []) or key in (s.get('character_asset_map') or {}).values())) or
            (kind == 'scene' and name == s.get('scene')) or
            (kind == 'prop' and name in s.get('props', []))]


def fingerprint(project):
    return hashlib.sha256(json.dumps({k: project.get(k) for k in ('script', 'assets', 'prompts', 'reference_sync')}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def require_synced(project, indexes):
    pending = [s['index'] for key in project.get('reference_sync', {}) for s in affected(project, key) if s['index'] in indexes]
    if pending:
        raise ValueError('参考图已更新，请先确认同步提示词（镜头：' + '、'.join(map(str, sorted(set(pending)))) + '）')


def register_reference_sync(ns):
    app = ns['app']

    @app.route('/api/project/<pid>/reference-sync', methods=['POST'])
    def reference_sync(pid):
        data = request.get_json(silent=True) or {}
        project = ns['load_project'](pid)
        if not project:
            return jsonify(ok=False, msg='项目不存在'), 404
        if data.get('apply'):
            with ns['PROJECT_IO_LOCK']:
                project = ns['load_project'](pid)
                draft = project.get('reference_sync_draft') or {}
                if not draft or draft.get('token') != data.get('token') or draft.get('base') != fingerprint(project):
                    return jsonify(ok=False, msg='图片或剧本已变化，请重新预览同步结果'), 409
                by_index = {s['index']: s for s in project['script']['shots']}
                for change in draft['changes']:
                    idx = change['index']
                    by_index[idx].update({k: change[k] for k in ('wardrobe', 'action')})
                    ns['_sync_current_shot_metadata'](project, idx, prompt=change['prompt'])
                    project.setdefault('prompts', {})[str(idx)] = change['prompt']
                    for shot in project.get('shots', []):
                        if shot['index'] == idx:
                            shot.update(reference_video_stale=True, wardrobe=change['wardrobe'], action=change['action'])
                for key, description in draft['descriptions'].items():
                    kind, name = key.split('_', 1)
                    group = {'char': 'characters', 'scene': 'scenes', 'prop': 'props'}[kind]
                    for item in project['script'].get(group, []):
                        if item.get('name') == name:
                            item['appearance' if kind == 'char' else 'description'] = description
                project['reference_sync'] = {}
                project.pop('reference_sync_draft', None)
                ns['save_project'](project)
            return jsonify(ok=True)
        pending = project.get('reference_sync') or {}
        if not pending:
            return jsonify(ok=False, msg='没有待同步的参考图'), 400
        base = fingerprint(project)
        descriptions, changes = {}, []
        ns['set_runtime_config'](ns['project_render_config'](project))
        try:
            for key in pending:
                kind, name = key.split('_', 1)
                description, error = ns['describe_uploaded_asset'](project['assets'][key]['path'], kind, name)
                if error or not description:
                    raise ValueError(error or '图片识别失败，请重试')
                descriptions[key] = description
            impacted = {s['index']: s for key in pending for s in affected(project, key)}
            rendered = {s['index']: s for s in project.get('shots', [])}
            for idx, shot in impacted.items():
                old = rendered.get(idx, {})
                prompt = (project.get('prompts') or {}).get(str(idx)) or old.get('prompt', '')
                relevant = {key: desc for key, desc in descriptions.items() if any(s['index'] == idx for s in affected(project, key))}
                text, error = ns['llm_chat']([{'role': 'user', 'content':
                    '根据新参考图描述同步本镜。只改对应资产的外观、服装、发型及与之冲突的动作细节；保留剧情、对白、人物身份、镜头时长、运镜和Picture编号。其他角色不变。资产名称可能含旧服装名，视觉描述优先。不可凭空增加配饰。\n'
                    + json.dumps({'new_references': relevant, 'shot': shot, 'prompt': prompt}, ensure_ascii=False)
                    + '\n仅返回JSON对象，含wardrobe、action、prompt三个非空字符串，prompt为完整视频生成提示词。'}], max_tokens=5000, temperature=0.2)
                if error:
                    raise ValueError(error)
                change = ns['parse_json_from_text'](text)
                if not isinstance(change, dict) or any(not isinstance(change.get(k), str) or not change[k].strip() for k in ('wardrobe', 'action', 'prompt')):
                    raise ValueError('AI同步结果不完整，请重试')
                changes.append(dict(index=idx, **{k: change[k] for k in ('wardrobe', 'action', 'prompt')}, before={'wardrobe': shot.get('wardrobe', ''), 'action': shot.get('action', ''), 'prompt': prompt}))
        except Exception as exc:
            return jsonify(ok=False, msg=str(exc)), 400
        finally:
            ns['clear_runtime_config']()
        with ns['PROJECT_IO_LOCK']:
            latest = ns['load_project'](pid)
            if fingerprint(latest) != base:
                return jsonify(ok=False, msg='识别期间图片或剧本已变化，请重新同步'), 409
            draft = dict(token=uuid.uuid4().hex, base=base, changes=changes, descriptions=descriptions)
            latest['reference_sync_draft'] = draft
            ns['save_project'](latest)
        return jsonify(ok=True, **draft)

    @app.before_request
    def guard_reference_sync():
        endpoint = request.endpoint or ''
        if endpoint in ('api_upload_asset', 'reference_sync'):
            pid = request.form.get('pid') if endpoint == 'api_upload_asset' else (request.view_args or {}).get('pid')
            project = ns['load_project'](pid) or {}
            awaiting_assets = project.get('custom_assets') and not project.get('assets_confirmed')
            pipeline_busy = (pid in ns.get('PIPELINE_CANCEL_EVENTS', {})
                             and pid not in REFERENCE_EDIT_WAITS and not awaiting_assets)
            busy = pipeline_busy or any(
                t.get('pid') == pid and t.get('status') == 'running'
                for name in ('RERENDER_TASKS', 'BATCH_RENDER_TASKS') for t in ns.get(name, {}).values())
            if busy:
                return jsonify(ok=False, msg='请等待当前项目生成结束，再换图或同步提示词'), 409
            return

        guarded = {'project_shot_rerender', 'project_shot_references', 'api_render_selected_stream', 'project_shot_replace'}
        args = request.view_args or {}
        pid = args.get('pid')
        indexes = [args['index']] if 'index' in args else []
        if endpoint == 'single_shot_generate':
            data = request.get_json(silent=True) or {}
            context = data.get('project_context') or {}
            pid = context.get('pid')
            indexes = [context.get('index')]
        elif endpoint not in guarded and request.path != '/api/pipeline/run':
            return
        if request.path == '/api/pipeline/run':
            pid = request.args.get('pid')
        if not pid:
            return
        project = ns['load_project'](pid)
        if not project:
            return jsonify(ok=False, error='项目不存在'), 404
        # 手动重制使用用户明确提供的新提示词，并由重制 worker 以
        # allow_disconnected=True 执行。它必须能修复上一镜失败或参考图
        # 已更新的镜头；如果在 before_request 这里先执行 require_synced，
        # 请求永远到不了重制 worker。
        if endpoint == 'project_shot_rerender' or endpoint == 'single_shot_generate':
            return
        if endpoint == 'api_render_selected_stream' and request.args.get('scope') == 'missing':
            # The route resolves the authoritative pending selection and checks it.
            return
        if not indexes:
            raw = request.args.get('indexes', '')
            indexes = [int(n) for n in raw.split(',') if n.isdigit()] or [s['index'] for s in (project.get('script') or {}).get('shots', [])]
        try:
            require_synced(project, indexes)
        except ValueError as exc:
            return jsonify(ok=False, error=str(exc), msg=str(exc), code='reference_sync_required'), 409
