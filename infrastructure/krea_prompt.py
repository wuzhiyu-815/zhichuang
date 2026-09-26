"""Load the shared Krea skill into the existing local prompt expander."""
from pathlib import Path
import re

SKILL_PATH = Path(__file__).resolve().parents[1] / 'skills/krea2-image-prompt/SKILL.md'


def apply_krea_skill(workflow, width, height):
    model = str(workflow.get('30:10', {}).get('inputs', {}).get('unet_name', ''))
    if not re.search(r'krea[ _-]*2(?:[^0-9]|$)', model, re.I):
        return False
    text = SKILL_PATH.read_text(encoding='utf-8')
    instructions = text.split('<!-- runtime:start -->', 1)[1].split('<!-- runtime:end -->', 1)[0].strip()
    workflow['30:18']['inputs']['value'] = instructions + f'\nActual output canvas: {int(width)} x {int(height)} pixels.'
    return True
