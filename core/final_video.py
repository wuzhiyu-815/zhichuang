"""Keep the last composed video accessible when its inputs change."""


def invalidate_final(project):
    current = project.pop('final', None)
    if current:
        project['previous_final'] = current


def available_final(project):
    return (project or {}).get('final') or (project or {}).get('previous_final')
