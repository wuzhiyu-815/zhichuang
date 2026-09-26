"""Persist AI edit conversations alongside the record they belong to."""
import copy
import time


def archive_edit(record, before, after, message, reply, model=None):
    timestamp = time.time()
    record.setdefault('chat_history', []).extend([
        {'role': 'user', 'content': message, 'created_at': timestamp},
        {'role': 'assistant', 'content': reply, 'created_at': timestamp},
    ])
    revisions = record.setdefault('edit_revisions', [])
    revisions.append({'version': len(revisions) + 1, 'created_at': timestamp,
                      'before': copy.deepcopy(before), 'after': copy.deepcopy(after),
                      'message': message, 'reply': reply, 'model': model})
