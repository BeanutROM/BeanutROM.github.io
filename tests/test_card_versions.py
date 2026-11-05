"""Rendered release version labels for stable, Beta, and Alpha projects."""
import json
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'site/app.js').read_text(encoding='utf-8')


class BadgeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.badges = []

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get('class', '')
        self.stack.append(cls)
        if tag == 'span' and cls in ('release-stage-badge', 'release-version-badge'):
            self.badges.append({'class': cls, 'text': '', 'attributes': dict(attrs)})

    def handle_data(self, data):
        if self.stack and self.stack[-1] in ('release-stage-badge', 'release-version-badge'):
            self.badges[-1]['text'] += data

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()


class CardVersionTests(unittest.TestCase):


    @unittest.skipUnless(shutil.which('node'), 'Node.js required for frontend behavior test')
    def test_actual_javascript_renders_all_release_stages_and_versions(self):
        # Evaluate the actual frontend formatter and card renderer in Node.
        # Stub unrelated browser helpers only, not release-badge logic.
        core = 'function releaseStage(p) {' + APP.split('  function releaseStage(p) {', 1)[1].split('  // Reserve a frame', 1)[0]
        projects = [
            {'id': 'stable', 'status': 'Released', 'release_tag': 'v1.0'},
            {'id': 'beta', 'status': 'Released', 'release_tag': 'v0.7-Beta', 'release_stage': 'Beta'},
            {'id': 'alpha', 'status': 'Released', 'release_tag': 'v0.4-Alpha', 'release_stage': 'Alpha'},
            {'id': 'beta2', 'status': 'Released', 'release_tag': 'v1.2-beta.2', 'release_stage': 'Beta'},
            {'id': 'rc', 'status': 'Released', 'release_tag': 'v2.3-rc1'},
            {'id': 'unreleased', 'status': 'In-Progress', 'release_tag': 'v3.0-Beta', 'release_stage': 'Beta'},
            {'id': 'missing', 'status': 'Released', 'release_tag': ''},
            {'id': 'escaped', 'status': 'Released', 'release_tag': 'v1.0<script>'},
        ]
        for p in projects:
            p['title'] = p['id']
            p['description'] = ''
            p['id'] = str(p['id'])
        js = f'''const vm = require('node:vm');
const escape = value => String(value ?? '').replace(/[&<>"']/g,
  char => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[char]));
const context = {{escape, state:{{expanded:null}}, safeUrl:()=>'',
  placeholder:()=>'<div class="poster"></div>', platformBadges:()=>'',
  shortDate:()=>'', starIcon:''}};
vm.createContext(context);
vm.runInContext({json.dumps(core)},context);
const examples = {json.dumps(projects)};
const results = examples.map(p=>({{
  id:p.id, label:context.versionLabel(p), base:context.versionBaseLabel(p),
  html:context.projectCard(p)
}}));
console.log(JSON.stringify(results));'''
        result = subprocess.run(['node', '-e', js], capture_output=True, text=True, check=True)
        parsed = {p['id']: p for p in json.loads(result.stdout)}
        expectations = {
            'stable': ('v1.0', [('release-version-badge','v1.0')]),
            'beta': ('v0.7 [BETA]', [('release-stage-badge','BETA'),('release-version-badge','v0.7')]),
            'alpha': ('v0.4 [ALPHA]', [('release-stage-badge','ALPHA'),('release-version-badge','v0.4')]),
            'beta2': ('v1.2-beta.2 [BETA]', [('release-stage-badge','BETA'),('release-version-badge','v1.2-beta.2')]),
            'rc': ('v2.3-rc1', [('release-version-badge','v2.3-rc1')]),
            'unreleased': ('v3.0-Beta', []),
            'missing': ('', []),
            'escaped': ('v1.0<script>', [('release-version-badge','v1.0<script>')]),
        }
        for key, (label, badges) in expectations.items():
            with self.subTest(key=key):
                data = parsed[key]
                self.assertEqual(data['label'], label)
                html = data['html']
                parser = BadgeParser()
                parser.feed(html)
                self.assertEqual([(b['class'],b['text']) for b in parser.badges], badges)
                if key == 'escaped':
                    self.assertNotIn('<script>', html)
                    self.assertIn('&lt;script&gt;', html)
                for badge in parser.badges:
                    if badge['class'] == 'release-version-badge':
                        self.assertEqual(badge['attributes']['title'], label)


if __name__ == '__main__':
    unittest.main()
