"""Small archive index, consulted before reading expensive project documents."""
import sqlite3

class WorkArchive:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS archived (kind TEXT, id TEXT, parent TEXT, PRIMARY KEY(kind,id,parent))')

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def ids(self, kind):
        with self.connect() as db:
            return {row[0] for row in db.execute('SELECT id FROM archived WHERE kind=?', (kind,))}

    def set(self, kind, ident, archived, children=()):
        with self.connect() as db:
            if archived:
                db.execute('INSERT OR IGNORE INTO archived VALUES (?,?,?)', (kind, ident, ''))
                if kind == 'series':
                    db.executemany('INSERT OR IGNORE INTO archived VALUES (?,?,?)', [('project', pid, ident) for pid in children])
            else:
                db.execute('DELETE FROM archived WHERE kind=? AND id=? AND parent=?', (kind, ident, ''))
                if kind == 'series':
                    db.execute('DELETE FROM archived WHERE kind=? AND parent=?', ('project', ident))
