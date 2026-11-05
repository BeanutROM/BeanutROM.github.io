"""Carousel selects a centered five-card window at each list position."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'site/app.js').read_text(encoding='utf-8')

class ShowcaseCarouselTests(unittest.TestCase):


    @unittest.skipUnless(shutil.which('node'),'Node.js required for actual window-selection test')
    def test_five_card_window_selection_and_edges(self):
        source = 'function showcaseWindow(index, total, slots) {' + JS.split('  function showcaseWindow(index, total, slots) {',1)[1].split('\n  function layoutShowcase',1)[0]
        runner = '''const vm=require('node:vm'); const ctx={}; vm.createContext(ctx); vm.runInContext(process.argv[1],ctx);
        console.log(JSON.stringify(Array.from({length:10},(_,i)=>({index:i,...ctx.showcaseWindow(i,10,5)}))));'''
        run = subprocess.run(['node','-e',runner,source],capture_output=True,text=True,check=True)
        rows=json.loads(run.stdout)
        self.assertEqual([r['start'] for r in rows],[0,0,0,1,2,3,4,5,5,5])
        self.assertTrue(all(r['count']==5 for r in rows))
        self.assertEqual([r['index']-r['start'] for r in rows],[0,1,2,2,2,2,2,2,3,4])


if __name__ == '__main__': unittest.main()
