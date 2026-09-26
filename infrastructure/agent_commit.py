"""Commit only an agent's shot-local changes onto the latest project."""
import copy


def commit(engine, project, index, baseline, maps=(), shot_fields=()):
    with engine.PROJECT_IO_LOCK:
        latest = engine.load_project(project['id'])
        if latest is None:
            raise ValueError('项目不存在')
        key = str(index)
        for name in maps:
            if key in project.get(name, {}):
                latest.setdefault(name, {})[key] = copy.deepcopy(project[name][key])
        source = next((s for s in project.get('shots', []) if s.get('index') == index), {})
        target = next((s for s in latest.get('shots', []) if s.get('index') == index), None)
        if target is not None:
            for field in shot_fields:
                if field in source:
                    target[field] = copy.deepcopy(source[field])
                else:
                    target.pop(field, None)
        new = [r for r in project.get('智能体决策记录', []) if r not in baseline]
        latest['智能体决策记录'] = (latest.get('智能体决策记录', []) + new)[-100:]
        engine.save_project(latest)
        return latest
