"""Validate H3 speaker headers without changing dialogue or reference identities."""
import re


def normalize_dialogue_boundaries(prompt):
    """Normalize only explicit, matching speaker headers; never rewrite dialogue."""
    # Split off dialogue bodies so header-like text spoken by a character is untouched.
    parts = re.split(r'(<d>\s*\[Chinese\].*?</d>)', prompt, flags=re.S)
    header = re.compile(
        r'(?:[*_`# ]*)<Subject[ \t]+(\d+)>[ \t]*\(S\1\)[ \t]+says[ \t]*[:：]\s*(?:[*_`# ]*)$'
    )
    for index in range(0, len(parts) - 1, 2):
        prefix = parts[index]
        match = header.search(prefix)
        if not match:
            continue
        before = prefix[:match.start()].rstrip(' \t\r\n')
        parts[index] = (before + '\n' if before else '') + f'<Subject {match[1]}> (S{match[1]}) says:\n'
    return ''.join(parts)


def dialogue_boundary_errors(prompt):
    errors = []
    for match in re.finditer(r'<d>\s*\[Chinese\]', prompt):
        prefix = prompt[:match.start()]
        header = re.search(r'(?:^|\n)<Subject\s+(\d+)>\s+\(S(\d+)\) says:\n[ \t]*$', prefix)
        if not header or header[1] != header[2]:
            errors.append('对白必须由独立的 <Subject N> (SN) says: 行直接引出，禁止夹入人物介绍')
    return list(dict.fromkeys(errors))
