"""Background episode exports with uniform video/audio streams."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from urllib.parse import unquote

from flask import jsonify, request, send_file


def compatible_streams(stream_sets):
    """Conservative stream-copy check, including codec initialization data."""
    keys = ('codec_type', 'codec_name', 'codec_tag_string', 'profile', 'level',
            'width', 'height', 'pix_fmt', 'sample_aspect_ratio', 'r_frame_rate',
            'time_base', 'sample_rate', 'channels', 'channel_layout',
            'sample_fmt', 'extradata_hash', 'color_range', 'color_space',
            'color_transfer', 'color_primaries', 'side_data_list')
    signatures = [[{key: stream.get(key) for key in keys} for stream in streams]
                  for streams in stream_sets]
    return bool(signatures and signatures[0]) and all(
        stream.get('codec_type') in ('video', 'audio') for stream in stream_sets[0]
    ) and all(signature == signatures[0] for signature in signatures[1:])


def register_episode_export(app, load_series, episode_status, outputs_dir, find_ffmpeg):
    jobs = {}
    lock = threading.Lock()
    root = Path(outputs_dir).resolve()
    export_root = root / '_episode_exports'

    def run(job, paths, ffmpeg):
        work = tempfile.mkdtemp(prefix='episode-merge-')
        try:
            probe = shutil.which('ffprobe') or str(Path(ffmpeg).with_name('ffprobe'))
            def info(path):
                return json.loads(subprocess.check_output(
                    [probe, '-v', 'error', '-show_streams', '-show_data_hash', 'sha256', '-of', 'json', str(path)], timeout=60))['streams']
            stream_sets = [info(path) for path in paths]
            if compatible_streams(stream_sets):
                with lock:
                    job.update(progress=10, msg='正在快速拼接（无需转码）')
                # Use controlled names so paths containing quotes/newlines remain safe.
                for i, path in enumerate(paths):
                    os.symlink(path, Path(work) / f'source_{i}.mp4')
                manifest = Path(work) / 'direct.txt'
                manifest.write_text(''.join(f"file 'source_{i}.mp4'\n" for i in range(len(paths))))
                try:
                    subprocess.run([ffmpeg, '-nostdin', '-y', '-v', 'error', '-f', 'concat', '-safe', '0',
                                    '-i', str(manifest), '-map', '0', '-c', 'copy', '-movflags', '+faststart', job['path']],
                                   check=True, capture_output=True, timeout=14400)
                    with lock:
                        job.update(status='done', progress=100, msg='快速拼接完成')
                    return
                except subprocess.CalledProcessError:
                    Path(job['path']).unlink(missing_ok=True)
            with lock:
                job.update(progress=0, msg='正在统一视频格式，耗时较长')
            first = next(s for s in stream_sets[0] if s['codec_type'] == 'video')
            width, height = int(first['width']) // 2 * 2, int(first['height']) // 2 * 2
            for i, path in enumerate(paths):
                streams = stream_sets[i]
                audio = any(s['codec_type'] == 'audio' for s in streams)
                cmd = [ffmpeg, '-nostdin', '-y', '-v', 'error', '-i', str(path)]
                if not audio:
                    cmd += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
                cmd += ['-map', '0:v:0', '-map', '0:a:0' if audio else '1:a:0',
                        '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30',
                        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
                        '-threads', '2', '-c:a', 'aac', '-ar', '48000', '-ac', '2',
                        '-af', 'apad', '-shortest', str(Path(work) / f'{i}.mp4')]
                subprocess.run(cmd, check=True, capture_output=True, timeout=14400)
                with lock:
                    job['progress'] = round((i + 1) / (len(paths) + 1) * 100)
            manifest = Path(work) / 'concat.txt'
            manifest.write_text(''.join(f"file '{i}.mp4'\n" for i in range(len(paths))))
            subprocess.run([ffmpeg, '-nostdin', '-y', '-v', 'error', '-f', 'concat', '-safe', '0',
                            '-i', str(manifest), '-c', 'copy', '-movflags', '+faststart', job['path']],
                           check=True, capture_output=True, timeout=14400)
            with lock:
                job.update(status='done', progress=100)
        except Exception:
            app.logger.exception('Episode merge failed')
            Path(job['path']).unlink(missing_ok=True)
            with lock:
                job.update(status='error', msg='合并失败，请检查成片是否可播放以及 FFmpeg 是否可用')
        finally:
            shutil.rmtree(work, ignore_errors=True)

    @app.post('/api/series/<series_id>/merge-download')
    def start(series_id):
        series = load_series(series_id)
        if not series:
            return jsonify(ok=False, msg='剧项目不存在'), 404
        data = request.get_json(silent=True) or {}
        ids = data.get('project_ids') if isinstance(data, dict) else None
        if not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids):
            return jsonify(ok=False, msg='请选择要合并的剧集'), 400
        selected = set(ids)
        episodes = sorted((ep for ep in episode_status(series).values() if ep.get('project_id') in selected), key=lambda ep: ep['episode'])
        if {ep['project_id'] for ep in episodes} != selected:
            return jsonify(ok=False, msg='所选剧集已变更，请刷新后重新选择'), 400
        paths = []
        for ep in episodes:
            url = ep.get('final') or ''
            path = (root / unquote(url.removeprefix('/file/outputs/'))).resolve()
            if not url.startswith('/file/outputs/') or not path.is_relative_to(root) or not path.is_file():
                return jsonify(ok=False, msg=f"第{ep['episode']}集尚无可用成片，请取消勾选后重试"), 400
            paths.append(path)
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            return jsonify(ok=False, msg='未检测到 FFmpeg'), 503
        with lock:
            # Keep completed exports available for a day; cap concurrent encoders.
            for key, old in list(jobs.items()):
                if old['status'] != 'running' and time.time() - old['created'] > 86400:
                    Path(old['path']).unlink(missing_ok=True)
                    del jobs[key]
            if sum(j['status'] == 'running' for j in jobs.values()) >= 2:
                return jsonify(ok=False, msg='已有合并任务进行中，请稍后重试'), 409
            export_root.mkdir(parents=True, exist_ok=True)
            token = uuid.uuid4().hex
            import re
            def safe_title(value):
                value = re.sub(r'[\\/:*?"<>|\r\n]+', '_', str(value or '').strip())
                return re.sub(r'_+', '_', value).strip(' ._')[:80] or '未命名'
            series_title = safe_title(series.get('name') or '剧集')
            if len(episodes) == 1:
                episode_title = safe_title(episodes[0].get('title') or f"第{episodes[0]['episode']}集")
                # Episode titles in older series often already include the series name.
                label = episode_title if episode_title.startswith(series_title) else f"{series_title}_{episode_title}"
                filename = f"{label}_成片.mp4"
            else:
                episode_titles = '、'.join(safe_title(ep.get('title') or f"第{ep['episode']}集") for ep in episodes)
                filename = f"{series_title}_{episode_titles[:120]}_合并成片.mp4"
            job = dict(status='running', progress=0, created=time.time(), path=str(export_root / f'{token}.mp4'),
                       filename=filename)
            jobs[token] = job
        threading.Thread(target=run, args=(job, paths, ffmpeg), daemon=True).start()
        return jsonify(ok=True, job_id=token)

    @app.get('/api/episode-exports/<token>')
    def status(token):
        with lock:
            job = jobs.get(token)
            if not job:
                return jsonify(ok=False, msg='合并任务不存在或已过期，请重新合并'), 404
            return jsonify(ok=True, status=job['status'], progress=job['progress'], msg=job.get('msg', ''))

    @app.get('/api/episode-exports/<token>/download')
    def download(token):
        with lock:
            job = jobs.get(token)
            if not job or job['status'] != 'done':
                return jsonify(ok=False, msg='合并尚未完成或已过期'), 404
            return send_file(job['path'], as_attachment=True, download_name=job['filename'])
