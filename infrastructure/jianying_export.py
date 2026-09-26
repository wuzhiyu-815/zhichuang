"""Portable Windows Jianying drafts containing original, editable video clips."""
import copy
import json
from pathlib import Path
import re
import tempfile
import threading
import time
import uuid
import zipfile
from urllib.parse import unquote, urlsplit

from flask import jsonify, request, send_file

BUNDLE = Path(__file__).with_name('jianying_bundle')
MARKER = '__JY_DRAFT_ROOT__'


def local_output(value, outputs):
    root = Path(outputs).resolve()
    value = str(value or '')
    if value.startswith('/file/outputs/'):
        path = root / unquote(urlsplit(value).path[len('/file/outputs/'):])
    else:
        path = Path(value)
        if not path.is_absolute():
            path = root.parent / path
    path = path.resolve()
    if not value or not path.is_relative_to(root) or not path.is_file():
        raise ValueError('没有可用的本地视频文件')
    return path


def select_clips(series, statuses, ids, load_project, outputs, mode):
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) for i in ids):
        raise ValueError('请先勾选要导出的剧集')
    selected = set(ids)
    episodes = sorted((ep for ep in statuses.values() if ep.get('project_id') in selected), key=lambda ep: ep['episode'])
    if {ep['project_id'] for ep in episodes} != selected:
        raise ValueError('所选剧集已变更，请刷新后重新选择')
    clips = []
    for ep in episodes:
        project = load_project(ep['project_id'])
        if not project:
            raise ValueError(f"第{ep['episode']}集项目不存在")
        if mode == 'episodes':
            try:
                path = local_output(project.get('final'), outputs)
            except ValueError as exc:
                raise ValueError(f"第{ep['episode']}集尚无可用成片") from exc
            clips.append(dict(path=path, episode=ep['episode'], index=None,
                              label=f"第{ep['episode']}集 · {project.get('title') or '成片'}", dialogue=[]))
            continue
        script = (project.get('script') or {}).get('shots') or []
        rendered = {str(s.get('index')): s for s in project.get('shots', [])}
        expected = script or list(rendered.values())
        if not expected:
            raise ValueError(f"第{ep['episode']}集没有镜头记录，可选择按整集成片导出")
        for source in sorted(expected, key=lambda s: int(s['index'])):
            index = source['index']
            shot = rendered.get(str(index)) or {}
            try:
                if shot.get('error'):
                    raise ValueError('镜头生成失败')
                path = local_output(shot.get('path') or shot.get('video_url'), outputs)
            except ValueError as exc:
                raise ValueError(f"第{ep['episode']}集镜头{index}未完成或素材缺失，请等待生成完成，或选择按整集成片导出") from exc
            clips.append(dict(path=path, episode=ep['episode'], index=index,
                              label=f"第{ep['episode']}集 · 镜头{index}", dialogue=source.get('dialogue') or []))
    return clips


def build_draft_zip(destination, name, clips, subtitles=False, progress=None):
    import pyJianYingDraft as draft
    report = progress or (lambda percent, message: None)
    report(2, '正在读取镜头信息')
    first = draft.VideoMaterial(str(clips[0]['path']))
    with tempfile.TemporaryDirectory(prefix='jianying-export-') as work:
        script = draft.DraftFolder(work).create_draft('draft', first.width, first.height, fps=24)
        script.append_track(draft.TrackSpec(draft.TrackType.video, name='视频'))
        if subtitles:
            script.append_track(draft.TrackSpec(draft.TrackType.text, name='对白字幕（需校对）'))
        cursor = 0
        manifest = []
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for number, clip in enumerate(clips):
                material = draft.VideoMaterial(str(clip['path']), material_name=clip['label'])
                duration = material.duration
                if duration <= 0:
                    raise ValueError(f"{clip['label']}的视频时长无效")
                media_path = f'media/{number + 1:05d}.mp4'
                # Save portable paths; the local importer resolves them after copying.
                material.path = f'{MARKER}/{media_path}'
                segment = draft.VideoSegment(material, draft.trange(cursor, duration))
                script.add_segment(segment, track='视频')
                lines = [d for d in clip['dialogue'] if isinstance(d, dict) and str(d.get('line') or '').strip()]
                if subtitles and lines:
                    for i, line in enumerate(lines):
                        start, end = duration * i // len(lines), duration * (i + 1) // len(lines)
                        speaker = str(line.get('speaker') or '').strip()
                        text = (speaker + '：' if speaker else '') + str(line['line']).strip()
                        caption = draft.TextSegment(text, draft.trange(cursor + start, end - start),
                                                    style=draft.TextStyle(size=6, align=1, auto_wrapping=True),
                                                    clip_settings=draft.ClipSettings(transform_y=-0.8))
                        script.add_segment(caption, track='对白字幕（需校对）')
                archive.write(clip['path'], f'draft/{media_path}')
                manifest.append(dict(episode=clip['episode'], shot=clip['index'], label=clip['label'],
                                     file=media_path, start_us=cursor, duration_us=duration))
                cursor += duration
                report(5 + round(90 * (number + 1) / len(clips)), f'正在打包素材 {number + 1}/{len(clips)}')
            script.save()
            draft_dir = Path(work) / 'draft'
            content = json.loads((draft_dir / 'draft_content.json').read_text(encoding='utf-8'))
            content.update(id=str(uuid.uuid4()).upper(), name=name)
            meta = json.loads((draft_dir / 'draft_meta_info.json').read_text(encoding='utf-8'))
            meta.update(draft_id=content['id'], draft_name=name, draft_fold_path=MARKER,
                        draft_root_path='', tm_duration=cursor, tm_draft_create=int(time.time() * 1e6),
                        tm_draft_modified=int(time.time() * 1e6))
            for filename, data in [('draft_content.json', content), ('draft_meta_info.json', meta),
                                   ('clip_manifest.json', manifest)]:
                archive.writestr('draft/' + filename, json.dumps(data, ensure_ascii=False))
            for filename in ('import.ps1', 'import.cmd', 'README.txt'):
                value = (BUNDLE / filename).read_text(encoding='utf-8').replace('\n', '\r\n')
                archive.writestr(filename, value.encode('utf-8-sig' if filename == 'import.ps1' else 'utf-8'))
    report(100, '剪映草稿包已就绪')


def register_jianying_export(app, load_series, episode_status, load_project, outputs_dir):
    root = Path(outputs_dir) / '_jianying_exports'
    jobs, lock = {}, threading.Lock()

    def public(job):
        return {key: job[key] for key in ('status', 'progress', 'msg')}

    def run(token, name, clips, subtitles):
        path = root / (token + '.zip')
        def report(progress, msg):
            with lock:
                jobs[token].update(progress=progress, msg=msg)
        try:
            build_draft_zip(path, name, clips, subtitles, report)
            with lock:
                jobs[token]['status'] = 'done'
        except Exception as exc:
            app.logger.exception('Jianying draft export failed')
            path.unlink(missing_ok=True)
            with lock:
                jobs[token].update(status='error', msg=str(exc) if isinstance(exc, ValueError) else '草稿打包失败，请稍后重试')
        finally:
            with lock:
                (root / (token + '.json')).write_text(json.dumps(jobs[token], ensure_ascii=False), encoding='utf-8')

    @app.post('/api/series/<series_id>/jianying-export', endpoint='jianying_export_start')
    def start(series_id):
        series = load_series(series_id)
        if not series:
            return jsonify(ok=False, msg='剧项目不存在'), 404
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(ok=False, msg='请求参数无效'), 400
        mode = data.get('mode', 'shots')
        if mode not in ('shots', 'episodes'):
            return jsonify(ok=False, msg='请选择按镜头或按整集导出'), 400
        subtitles = data.get('subtitles', False)
        if not isinstance(subtitles, bool) or (subtitles and mode != 'shots'):
            return jsonify(ok=False, msg='可编辑对白字幕仅支持按镜头导出'), 400
        try:
            clips = select_clips(series, episode_status(series), data.get('project_ids'),
                                 load_project, outputs_dir, mode)
        except ValueError as exc:
            return jsonify(ok=False, msg=str(exc)), 400
        with lock:
            if sum(j['status'] == 'running' for j in jobs.values()) >= 2:
                return jsonify(ok=False, msg='已有两个草稿打包任务，请稍后重试'), 409
            root.mkdir(parents=True, exist_ok=True)
            # Completed bundles expire after a day. Never remove active downloads here.
            for record in root.glob('*.json'):
                if time.time() - record.stat().st_mtime > 86400:
                    old = jobs.get(record.stem)
                    if not old or old['status'] != 'running':
                        record.with_suffix('.zip').unlink(missing_ok=True)
                        record.unlink(missing_ok=True)
                        jobs.pop(record.stem, None)
            token = uuid.uuid4().hex
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(series.get('name') or '剧集'))[:70].strip('. ') or '剧集'
            name += '_剪映草稿'
            jobs[token] = dict(status='running', progress=0, msg='正在准备草稿素材', filename=name + '.zip')
        threading.Thread(target=run, args=(token, name, copy.deepcopy(clips), subtitles), daemon=True).start()
        return jsonify(ok=True, job_id=token)

    def get_job(token):
        if not re.fullmatch(r'[0-9a-f]{32}', token):
            return None
        job = jobs.get(token)
        if job is None:
            try:
                job = json.loads((root / (token + '.json')).read_text(encoding='utf-8'))
            except (OSError, ValueError):
                return None
        return job

    @app.get('/api/jianying-exports/<token>', endpoint='jianying_export_status')
    def status(token):
        with lock:
            job = get_job(token)
            if not job:
                return jsonify(ok=False, msg='草稿任务不存在或已过期，请重新导出'), 404
            return jsonify(ok=True, **public(job))

    @app.get('/api/jianying-exports/<token>/download', endpoint='jianying_export_download')
    def download(token):
        with lock:
            job = get_job(token)
            path = root / (token + '.zip')
            if not job or job['status'] != 'done' or not path.is_file():
                return jsonify(ok=False, msg='草稿尚未准备完成或已过期'), 404
            return send_file(path, as_attachment=True, download_name=job['filename'])
