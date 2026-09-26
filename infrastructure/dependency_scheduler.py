"""Schedule independent shots concurrently; never release a failed predecessor."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from infrastructure.shot_continuity import requires_previous_frame


def resolve_selection(shots, indexes, validate_external):
    """Include unavailable predecessors, reusing valid external videos when possible."""
    by_index = {s['index']: s for s in shots}
    selected = set(indexes)

    def ancestors(index):
        chain, seen = [], {index}
        while True:
            if index not in by_index:
                raise ValueError(f'第{index}镜不存在，无法补齐前置镜头')
            plan = by_index[index].get('continuity') or {}
            if not plan:
                raise ValueError(f'第{index}镜缺少衔接计划')
            if not requires_previous_frame(by_index[index]):
                return chain
            parent = plan.get('previous_index')
            if parent is None:
                raise ValueError(f'第{index}镜缺少前置镜头编号')
            if parent in seen:
                raise ValueError('镜头衔接依赖形成循环')
            seen.add(parent)
            chain.append(parent)
            index = parent

    # Inspect the full chain even if a cached predecessor is valid: a selected
    # ancestor will invalidate cached intermediate shots once it is regenerated.
    pending = list(selected)
    while pending:
        index = pending.pop()
        chain = ancestors(index)
        if not chain or chain[0] in selected:
            continue
        include = bool(set(chain) & selected)
        if not include:
            try:
                validate_external(by_index[index])
            except ValueError:
                include = True
        if include:
            selected.add(chain[0])
            pending.append(chain[0])
            # Newly included ancestors may invalidate another selected chain.
            pending.extend(i for i in selected if i not in pending and i != chain[0])
    return sorted(selected)


def run(shots, indexes, worker, completed, validate_external, workers=2, cancelled=lambda: False):
    selected = set(indexes)
    by_index = {s['index']: s for s in shots}
    if selected - by_index.keys():
        raise ValueError('选中的镜头不存在')
    dependencies = {}
    for index in selected:
        plan = by_index[index].get('continuity') or {}
        if not plan:
            raise ValueError(f'第{index}镜缺少衔接计划')
        parent = plan.get('previous_index') if requires_previous_frame(by_index[index]) else None
        if parent is not None and parent not in selected:
            validate_external(by_index[index])
        dependencies[index] = {parent} if parent in selected else set()
    # Validate before any expensive work is submitted.
    remaining = set(selected)
    while remaining:
        ready = {i for i in remaining if not dependencies[i] & remaining}
        if not ready:
            raise ValueError('镜头衔接依赖形成循环')
        remaining -= ready
    pending, done, failures, active = set(selected), set(), {}, {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        while pending or active:
            if cancelled():
                for i in pending:
                    failures[i] = '任务已取消'
                pending.clear()
            blocked = {i for i in pending if dependencies[i] & failures.keys()}
            for i in blocked:
                failures[i] = '前置镜头失败，未提交渲染'
            pending -= blocked
            ready = sorted(i for i in pending if dependencies[i] <= done)
            for i in ready[:max(0, workers-len(active))]:
                pending.remove(i)
                active[pool.submit(worker, i)] = i
            if not active:
                continue
            finished, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
            for future in finished:
                index = active.pop(future)
                try:
                    result = future.result()
                    completed(index, result)
                    done.add(index)
                except Exception as exc:
                    failures[index] = str(exc)
    if failures:
        raise ValueError('；'.join(f'第{i}镜：{error}' for i,error in sorted(failures.items())))
    return done


def render_groups(shots):
    """Expose independent chains without weakening explicit continuity edges."""
    groups, membership = [], {}
    for shot in shots:
        index = shot['index']
        plan = shot.get('continuity') or {}
        if not plan or plan.get('transition') not in ('opening', 'cut', 'continuous'):
            raise ValueError(f'第{index}镜缺少有效衔接计划')
        if requires_previous_frame(shot):
            parent = plan.get('previous_index')
            if parent not in membership:
                raise ValueError(f'第{index}镜前置镜头不存在或顺序错误')
            group = membership[parent]
        else:
            group = {'id': len(groups) + 1, 'indexes': [], 'reason': plan.get('reason') or '独立首镜'}
            groups.append(group)
        group['indexes'].append(index)
        membership[index] = group
    return groups
