"""按项目保存技能调用快照，不把密钥和不可序列化回调写入记录。"""
import logging
import re
import time
import uuid
from pathlib import Path
from .storage import JSON存储


def snapshot(value):
    if isinstance(value, dict):
        return {str(k): ('[REDACTED]' if any(word in str(k).lower()
                for word in ('password', 'secret', 'token', 'api_key', 'apikey', 'authorization', '密码', '密钥'))
                else snapshot(v)) for k, v in value.items() if not callable(v)}
    if isinstance(value, (list, tuple)):
        return [snapshot(v) for v in value if not callable(v)]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return '[非JSON对象: ' + type(value).__name__ + ']'


class RunArchive:
    def __init__(self, storage_provider):
        self.storage_provider = storage_provider

    def start(self, skill, project, parameters):
        if not isinstance(project, dict) or not project.get('id'):
            return None
        storage = self.storage_provider()
        root = Path(storage.path(project['id'])).parent
        agent = (project.get('协同状态') or {}).get('当前智能体') or 'skills'
        agent = re.sub(r'[^\w-]', '_', str(agent))[:80] or 'skills'
        invocation = uuid.uuid4().hex
        directory = root / 'runs' / agent / invocation
        directory.mkdir(parents=True, exist_ok=False)
        writer = JSON存储(directory, lambda key: key + '.json')
        metadata = dict(id=invocation, pipeline_run_id=project.get('run_id'),
                        agent=agent, skill=skill, started_at=time.time(), status='running')
        writer.save('run', metadata)
        # 当前项目输入完整保存；累积日志另在项目状态中，避免快照递归膨胀。
        context = {k: v for k, v in project.items() if k not in
                   ('运行记录', '技能调用记录', '智能体通信记录', '智能体决策记录')}
        writer.save('input', snapshot(dict(project=context, parameters=parameters or {})))
        return writer, metadata

    def finish(self, handle, result):
        if handle is None:
            return
        writer, metadata = handle
        writer.save('output', snapshot(result.转字典()))
        metadata.update(finished_at=time.time(), status='succeeded' if result.成功 else 'failed')
        metadata['duration_seconds'] = metadata['finished_at'] - metadata['started_at']
        writer.save('run', metadata)

    def safely(self, method, *args):
        try:
            return getattr(self, method)(*args)
        except Exception:
            logging.getLogger(__name__).exception('无法保存技能调试记录：%s', method)
            return None
