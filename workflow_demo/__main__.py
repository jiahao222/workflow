"""Run the offline workflow example: python -m workflow_demo demo."""
import argparse
import json
from pathlib import Path
from .queue import TaskQueue
from .worker import Worker

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['demo'])
    parser.add_argument('--workspace', default='.local')
    args = parser.parse_args()
    root = Path(args.workspace)
    brief = json.loads((Path(__file__).resolve().parent.parent / 'examples/fictional_brief.json').read_text(encoding='utf-8'))
    queue = TaskQueue(root / 'jobs.sqlite3')
    wid = queue.submit(brief['title'], brief)
    Worker(queue, root / 'output').drain()
    print(json.dumps({'workflow_id':wid,'state':queue.inspect(wid)['workflow']['state'],
                      'output_dir':str(root/'output'/wid)},indent=2))

if __name__ == '__main__':
    main()
