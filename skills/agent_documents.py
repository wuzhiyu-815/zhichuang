"""Load project-owned agent skill documents and their bundled text references."""
from pathlib import Path


def load_agent_skill(base_dir, name, stage):
    agent = {"video_prompt": "prompts", "script": "script"}.get(stage)
    if not agent or Path(name).name != name:
        return ""
    root = Path(base_dir) / "agents" / agent / "skills" / name
    entry = root / "SKILL.md"
    if not entry.is_file():
        return ""
    documents = [entry]
    references = root / "references"
    if references.is_dir():
        documents.extend(sorted(p for p in references.rglob('*')
                                if p.is_file() and p.suffix.lower() in {'.md', '.txt', '.json'}))
    return '\n\n'.join(f'【{p.relative_to(root)}】\n{p.read_text(encoding="utf-8-sig")}'
                       for p in documents)
