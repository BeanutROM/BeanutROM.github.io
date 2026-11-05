"""keep 20 newest catalog workflow runs without touching live runs."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
YAML = (ROOT / '.github/workflows/pages.yml').read_text(encoding='utf-8')


def retention_script():
    """Extract the inline script exactly as the github-script action runs it."""
    section = YAML.split('\n  prune-history:', 1)[-1]
    match = re.search(r'(?m)^          script: \|\n((?:^            .*\n|^\n)+)', section)
    if not match:
        raise AssertionError('Missing history retention script')
    return textwrap.dedent(match.group(1))


class HistoryRetentionTests(unittest.TestCase):

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for JS sandbox tests')
    def test_js_retains_newest_twenty_and_protects_unfinished_and_current(self):
        from datetime import datetime, timedelta, timezone
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        runs = [{'id': n, 'status': 'completed',
                 'created_at': (start + timedelta(minutes=n)).isoformat()}
                for n in range(1, 36)]
        runs[5]['status'] = 'in_progress'  # older active run must survive
        runs[4]['status'] = 'queued'        # older queued run must survive
        expected = set(range(1, 16)) - {3, 5, 6}
        deleted = self._run(runs, current_id=3)
        self.assertEqual(set(deleted), expected)

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for JS sandbox tests')
    def test_js_preserves_short_history_and_handles_failed_deletions(self):
        from datetime import datetime, timedelta, timezone
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        runs = [{'id': n, 'status': 'completed',
                 'created_at': (start + timedelta(minutes=n)).isoformat()}
                for n in range(1, 19)]
        self.assertEqual(self._run(runs, current_id=19), [])
        runs += [{'id': n, 'status': 'completed',
                  'created_at': (start + timedelta(minutes=n)).isoformat()}
                 for n in range(19, 26)]
        self.assertEqual(set(self._run(runs, current_id=25, fails={1, 2})), {3, 4, 5})

    @unittest.skipUnless(shutil.which('node'), 'Node.js needed for JS sandbox tests')
    def test_js_paginates_large_history_and_deletes_only_older_completed_runs(self):
        from datetime import datetime, timedelta, timezone
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        runs = [{'id': n, 'status': 'completed',
                 'created_at': (start + timedelta(minutes=n)).isoformat()}
                for n in range(1, 246)]
        # These are older than the 20 newest, but still in progress.
        runs[1]['status'] = 'in_progress'
        runs[2]['status'] = 'queued'
        deleted = self._run(runs, current_id=1)
        expected = set(range(1, 226)) - {1, 2, 3}
        self.assertEqual(set(deleted), expected)
        self.assertEqual(len(deleted), len(expected))


    @staticmethod
    def _run(runs, current_id, fails=()):
        js = r'''
const input = INPUT;
const deleted = [];
const warnings = [];
const context = {repo: {owner:'demo',repo:'catalog'}, runId:input.current};
const core = {warning: x => warnings.push(x), info: x => {}};
const github = {
  rest: {actions: {
    listWorkflowRuns: () => {},
    deleteWorkflowRun: async ({run_id}) => {
      if (input.fails.includes(run_id)) throw new Error('test failure');
      deleted.push(run_id);
    }
  }},
  paginate: async (method, args, map) => {
    if (args.workflow_id !== 'pages.yml' || args.per_page !== 100) {
      throw new Error('Cleanup would affect the wrong workflow or pagination');
    }
    if (map !== undefined) {
      throw new Error('Use the normalized array from paginate(), not a response map');
    }
    // Octokit flattens the API's {workflow_runs: [...]} pages to this array.
    return input.runs;
  }
};
(async () => { SCRIPT })().then(() => {
  process.stdout.write(JSON.stringify({deleted,warnings}));
}).catch(error => { console.error(error); process.exitCode=1; });
'''
        js = js.replace('INPUT', json.dumps({'runs':runs,'current':current_id,'fails':list(fails)}))
        js = js.replace('SCRIPT', retention_script())
        process = subprocess.run(['node','-e',js], capture_output=True, text=True, timeout=20)
        if process.returncode:
            raise AssertionError(process.stderr)
        result=json.loads(process.stdout)
        if fails:
            assert len(result['warnings']) == len(fails)
        return result['deleted']


if __name__ == '__main__':
    unittest.main()
