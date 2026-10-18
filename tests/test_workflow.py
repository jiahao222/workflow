import concurrent.futures
import json
import tempfile
import unittest
from pathlib import Path

from workflow_demo.queue import TaskQueue, LeaseLost
from workflow_demo.worker import Worker
from workflow_demo.pipeline import analyze, storyboard, prompts, clean_filename

SAMPLE = Path(__file__).parent.parent / 'examples' / 'fictional_brief.json'

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.q = TaskQueue(self.path / 'tasks.db')
        self.brief = json.loads(SAMPLE.read_text(encoding='utf-8'))
        self.w = self.q.submit('test', self.brief, now=100)

    def test_one_worker_claims(self):
        task = self.q.claim('a',now=100,lease_seconds=10)
        self.assertIsNotNone(task)
        self.assertIsNone(self.q.claim('b',now=101))
        self.assertEqual(task['id'],self.q.claim('b',now=111)['id'])
        with self.assertRaises(LeaseLost):
            self.q.complete(task['id'],'a',{},now=112)

    def test_atomic_handoff(self):
        task = self.q.claim('a',now=100,lease_seconds=10)
        self.q.complete(task['id'],'a',{'normalized':True},now=101)
        items = self.q.inspect(self.w)['tasks']
        self.assertEqual([x['stage'] for x in items], ['analyze','storyboard'])
        self.assertEqual(items[1]['payload'],{'normalized':True})
        with self.assertRaises(LeaseLost):
            self.q.complete(task['id'],'a',{},now=102)

    def test_retry_and_terminal_error(self):
        for index,moment in enumerate((100,103,108),1):
            task = self.q.claim('a',now=moment,lease_seconds=10)
            self.assertEqual(task['attempts'],index)
            self.q.fail(task['id'],'a',now=moment+1)
        self.assertEqual(self.q.inspect(self.w)['workflow']['state'],'failed')

    def test_cancel_revokes_lease(self):
        task = self.q.claim('a',now=100,lease_seconds=10)
        self.q.cancel(self.w)
        with self.assertRaises(LeaseLost):
            self.q.complete(task['id'],'a',{},now=101)
        self.assertEqual(self.q.inspect(self.w)['workflow']['state'],'cancelled')

    def test_exhausted_expired_leases(self):
        for moment in (100,111,122):
            self.q.claim('a',now=moment,lease_seconds=10)
        self.assertIsNone(self.q.claim('b',now=133))
        self.assertEqual(self.q.inspect(self.w)['workflow']['state'],'failed')

    def test_parallel_claim_is_unique(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda i: self.q.claim(f'w{i}',now=100,lease_seconds=10),range(8)))
        self.assertEqual(sum(x is not None for x in results),1)

    def test_end_to_end(self):
        wid = self.q.submit('real demo',self.brief)
        self.assertEqual(Worker(self.q,self.path/'outputs').drain(),10)
        self.assertEqual(self.q.inspect(wid)['workflow']['state'],'succeeded')
        result = json.loads((self.path/'outputs'/wid/'delivery.json').read_text())
        self.assertEqual(len(result['clips']),3)
        self.assertEqual(result['render_backend'],'mock')

    def test_prompt_has_no_vendor_details(self):
        pack = prompts(storyboard(analyze(self.brief)))
        self.assertEqual(len(pack['shots']),3)
        self.assertIn('original animated scene',pack['shots'][0]['prompt'])
        self.assertNotIn('http',pack['shots'][0]['prompt'])
        self.assertEqual(clean_filename('../../secret'),'secret')

if __name__ == '__main__':
    unittest.main()
