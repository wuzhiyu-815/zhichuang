"""Disk-backed rerender receipts; a prior shot is never proof of completion."""
from pathlib import Path
import os
import time
import subprocess
from core.storage import JSON存储
from infrastructure.comfy_client import Comfy客户端


def store(root, pid):
    return JSON存储(Path(root) / pid / 'rerender_tasks', lambda key: key + '.json')


def recoverable(task):
    if not task.get('prompt_id') or not task.get('node_url'):
        return False
    if task.get('status') == 'running':
        return True
    message = str(task.get('msg', '')).lower()
    return task.get('status') == 'error' and any(token in message for token in (
        '历史接口返回 http', '历史连接异常', '生成超时', 'timed out',
        'connection', '502', '503', '504', '下载返回空文件'))


def recover(task, engine):
    if not task.get('prompt_id') or not task.get('node_url'):
        return dict(task, status='error', msg='服务中断，缺少生成回执；请核查节点，勿重复提交')
    client = Comfy客户端(lambda: task['node_url'])
    history, error = client.历史(task['prompt_id'])
    if not history:
        return dict(task, status='running', msg=error or '正在等待原生成任务', phase='恢复原任务')
    status = history.get('status', {})
    if status.get('status_str') == 'error':
        return dict(task, status='error', msg='原生成任务失败')
    if not status.get('completed'):
        return dict(task, status='running', phase='恢复原任务')
    candidates = [item for output in history.get('outputs', {}).values()
                  for key in ('images', 'gifs', 'videos') for item in output.get(key, [])
                  if str(item.get('filename', '')).lower().endswith(('.mp4', '.webm'))]
    if len(candidates) != 1:
        return dict(task, status='error', msg='生成结果视频不唯一，请人工核查')
    pid, index = task['pid'], task['index']
    # Batch/bridge renders use the same durable receipt mechanism as manual
    # rerenders, but their successful result belongs at the canonical shot
    # path.  Keeping this branch here means a service restart can finish an
    # already-submitted ComfyUI job without submitting a duplicate job.
    is_batch = task.get('kind') == 'batch'
    path = Path(engine.OUTPUTS_DIR) / pid / 'versions' / f'shot_{index:02d}' / (task['id'] + '.mp4')
    path.parent.mkdir(parents=True, exist_ok=True)
    client.下载(candidates[0], str(path))
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-f', 'null', '-'], check=True, timeout=120, capture_output=True)
    with engine.PROJECT_IO_LOCK:
        receipts = store(engine.PROJECTS_DIR, pid)
        for key in receipts.keys():
            newer = receipts.load(key) or {}
            if (newer.get('index') == index and newer.get('id') != task['id']
                    and newer.get('created', 0) > task.get('created', 0)):
                return dict(task, status='superseded', msg='已有更新的生成任务；原结果已保存在历史目录')
        project = engine.load_project(pid)
        shot = next((s for s in project.get('shots', []) if s.get('index') == index), None)
        if shot is None:
            script_shot = next((s for s in (project.get('script') or {}).get('shots', []) if s.get('index') == index), None)
            if script_shot is None:
                return dict(task, status='error', msg='项目中找不到原镜头；视频已保存在恢复目录')
            shot = dict(script_shot)
            project.setdefault('shots', []).append(shot)
        receipt = project.get('rerender_latest', {}).get(str(index))
        if not is_batch and receipt != task['id']:
            return dict(task, status='error', msg='已有更新的重制任务；本次视频已保存在历史目录')
        engine._archive_before_overwrite(project, index)
        if is_batch:
            import shutil
            canonical = Path(engine.OUTPUTS_DIR) / pid / f'shot_{index:02d}.mp4'
            staging = canonical.with_suffix('.recovering')
            shutil.copyfile(path, staging)
            os.replace(staging, canonical)
            shot.update(path=os.path.join('outputs', pid, f'shot_{index:02d}.mp4'),
                        video_url=f'/file/outputs/{pid}/shot_{index:02d}.mp4?t={int(time.time())}',
                        prompt=task.get('prompt') or shot.get('prompt', ''),
                        duration=task.get('duration', shot.get('duration', 8)),
                        camera=task.get('camera', shot.get('camera', '')),
                        audio_review={'status': 'pending', 'passed': False})
        else:
            shot.update(path=str(path), video_url=f'/file/outputs/{pid}/versions/shot_{index:02d}/{task["id"]}.mp4',
                        rendered_prompt=task.get('prompt'), audio_review={'status': 'pending', 'passed': False})
        shot.pop('error', None)
        engine.invalidate_final(project)
        engine.save_project(project)
    return dict(task, status='done', video_url=shot['video_url'], msg='已恢复生成结果；审核待完成')
