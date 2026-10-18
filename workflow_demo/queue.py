"""SQLite durable queue: leases, atomic handoff, progress, retries and cancellation."""
import json
import sqlite3
import time
import uuid
from pathlib import Path

STAGES = ('analyze', 'storyboard', 'prompts', 'render', 'deliver')

class LeaseLost(RuntimeError):
    pass

class TaskQueue:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS workflows (
              id TEXT PRIMARY KEY, title TEXT NOT NULL,
              state TEXT NOT NULL DEFAULT 'running');
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
              stage TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
              payload TEXT NOT NULL, result TEXT, created REAL NOT NULL,
              ready REAL NOT NULL, owner TEXT, lease_until REAL,
              attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
              error TEXT, UNIQUE(workflow_id, stage));
            CREATE TABLE IF NOT EXISTS progress (
              id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT,
              stage TEXT, percent INTEGER, event TEXT, at REAL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=20000')
        return db

    @staticmethod
    def enc(value):
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def item(row):
        if row is None: return None
        out = dict(row)
        for key in ('payload', 'result'):
            if key in out and out[key] is not None: out[key] = json.loads(out[key])
        return out

    def _put(self, db, workflow_id, stage, payload, now):
        db.execute("""INSERT OR IGNORE INTO tasks
            (id,workflow_id,stage,payload,created,ready)
            VALUES(?,?,?,?,?,?)""",
            (uuid.uuid4().hex, workflow_id, stage, self.enc(payload), now, now))

    def submit(self, title, payload, *, now=None):
        now = time.time() if now is None else now
        wid = 'wf-' + uuid.uuid4().hex[:12]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO workflows(id,title,state) VALUES(?,?,?)', (wid,title,'running'))
            self._put(db,wid,STAGES[0],payload,now)
        return wid

    def claim(self, worker_id, *, now=None, lease_seconds=60):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("""SELECT t.* FROM tasks t JOIN workflows w ON w.id=t.workflow_id
                WHERE w.state='running' AND t.attempts<t.max_attempts AND
                ((t.state='pending' AND t.ready<=?) OR
                 (t.state='running' AND t.lease_until<=?))
                ORDER BY t.created,t.rowid LIMIT 1""",(now,now)).fetchone()
            if row is None:
                db.execute("""UPDATE tasks SET state='failed',error='LeaseExhausted'
                    WHERE state='running' AND lease_until<=? AND attempts>=max_attempts""",(now,))
                db.execute("""UPDATE workflows SET state='failed' WHERE id IN
                    (SELECT workflow_id FROM tasks WHERE state='failed') AND state='running'""")
                return None
            db.execute("""UPDATE tasks SET state='running',attempts=attempts+1,
                owner=?,lease_until=?,error=NULL WHERE id=?""",
                (worker_id,now+lease_seconds,row['id']))
            return self.item(db.execute('SELECT * FROM tasks WHERE id=?',(row['id'],)).fetchone())

    def heartbeat(self, task_id, worker_id, *, now=None, lease_seconds=60):
        now = time.time() if now is None else now
        with self.connect() as db:
            cur = db.execute("""UPDATE tasks SET lease_until=? WHERE
                id=? AND owner=? AND state='running' AND lease_until>?""",
                (now+lease_seconds,task_id,worker_id,now))
            if cur.rowcount != 1: raise LeaseLost('Lease no longer active')

    def complete(self, task_id, worker_id, result, *, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("""SELECT t.*,w.state AS workflow_state
                FROM tasks t JOIN workflows w ON w.id=t.workflow_id
                WHERE t.id=?""",(task_id,)).fetchone()
            if (row is None or row['state']!='running' or row['workflow_state']!='running'
                    or row['owner']!=worker_id or row['lease_until']<=now):
                raise LeaseLost('Stale or cancelled lease')
            db.execute("""UPDATE tasks SET state='succeeded',result=?,owner=NULL,
                lease_until=NULL WHERE id=?""",(self.enc(result),task_id))
            position = STAGES.index(row['stage'])
            if position + 1 < len(STAGES):
                self._put(db,row['workflow_id'],STAGES[position+1],result,now)
            else:
                db.execute("UPDATE workflows SET state='succeeded' WHERE id=?",(row['workflow_id'],))

    def fail(self, task_id, worker_id, *, now=None, error_type='StageError'):
        now = time.time() if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("""SELECT * FROM tasks WHERE id=? AND owner=?
                AND state='running' AND lease_until>?""",(task_id,worker_id,now)).fetchone()
            if row is None: raise LeaseLost('Stale or cancelled lease')
            exhausted = row['attempts']>=row['max_attempts']
            delay = min(60, 2**max(0,row['attempts']-1))
            db.execute("""UPDATE tasks SET state=?,ready=?,owner=NULL,
                lease_until=NULL,error=? WHERE id=?""",
                ('failed' if exhausted else 'pending',
                 now if exhausted else now+delay,error_type[:72],task_id))
            if exhausted:
                db.execute("UPDATE workflows SET state='failed' WHERE id=?",(row['workflow_id'],))

    def cancel(self, workflow_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE workflows SET state='cancelled' WHERE id=? AND state='running'",(workflow_id,))
            db.execute("""UPDATE tasks SET state='cancelled',owner=NULL,lease_until=NULL
                WHERE workflow_id=? AND state IN ('running','pending')""",(workflow_id,))

    def progress(self, task_id, stage, percent, event):
        with self.connect() as db:
            db.execute('INSERT INTO progress(task_id,stage,percent,event,at) VALUES(?,?,?,?,?)',
                       (task_id,stage,max(0,min(100,int(percent))),str(event)[:32],time.time()))

    def inspect(self, workflow_id):
        with self.connect() as db:
            workflow = db.execute('SELECT id,title,state FROM workflows WHERE id=?',(workflow_id,)).fetchone()
            if workflow is None: raise KeyError(workflow_id)
            tasks = db.execute('SELECT * FROM tasks WHERE workflow_id=? ORDER BY created,rowid',(workflow_id,)).fetchall()
            events = db.execute("""SELECT stage,percent,event FROM progress WHERE task_id IN
                (SELECT id FROM tasks WHERE workflow_id=?) ORDER BY id""",(workflow_id,)).fetchall()
            return {'workflow':dict(workflow),'tasks':[self.item(x) for x in tasks],
                    'progress':[dict(x) for x in events]}
