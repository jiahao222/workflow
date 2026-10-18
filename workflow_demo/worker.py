"""Worker loop. Only synthetic inputs; no network requests."""
import logging
from pathlib import Path
from .queue import LeaseLost, TaskQueue
from .pipeline import MockVideoBackend, clean_filename, execute

log = logging.getLogger(__name__)

class Worker:
    def __init__(self, queue: TaskQueue, output_dir, *, name='demo-worker', backend=None):
        self.queue = queue
        self.output_dir = Path(output_dir)
        self.name = name
        self.backend = backend or MockVideoBackend()

    def once(self):
        task = self.queue.claim(self.name, lease_seconds=60)
        if task is None: return False
        self.queue.progress(task['id'], task['stage'], 5, 'claimed')
        try:
            result = execute(task['stage'], task['payload'],
                             self.output_dir / clean_filename(task['workflow_id']), self.backend)
            self.queue.heartbeat(task['id'], self.name, lease_seconds=60)
            self.queue.complete(task['id'], self.name, result)
        except Exception as exc:
            log.warning('task=%s error_type=%s', task['id'], type(exc).__name__)
            try:
                self.queue.fail(task['id'], self.name, error_type=type(exc).__name__)
            except LeaseLost:
                log.warning('task=%s stale lease', task['id'])
        else:
            self.queue.progress(task['id'], task['stage'], 100, 'completed')
        return True

    def drain(self, limit=100):
        count = 0
        while count < limit and self.once():
            count += 1
        return count
