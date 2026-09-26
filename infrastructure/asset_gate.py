"""Shared prerequisite for project video prompts and rendering."""
from pathlib import Path


def require_assets(project, base_dir, require_confirmation=True):
    missing=[]
    script=project.get('script') or {}
    assets=project.get('assets') or {}
    for group,prefix in [('characters','char'),('scenes','scene'),('props','prop')]:
        for item in script.get(group) or []:
            name=item.get('name')
            if not name:
                continue
            entry=assets.get(prefix+'_'+name) or {}
            path=Path(entry.get('path') or '')
            if not path.is_absolute():
                path=Path(base_dir)/path
            if not entry.get('path') or not path.is_file() or path.stat().st_size == 0:
                missing.append(name)
    if missing:
        raise ValueError('资产尚未生成完整，不能生成分镜提示词或视频：'+ '、'.join(missing[:8]))
    if require_confirmation and not (project.get('asset_confirm') or {}).get('__all__',{}).get('continue'):
        raise ValueError('请先确认角色与素材，再进入分镜制作')
