"""Media filtering classifies screenshots and videos using the real frontend logic."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'site/app.js').read_text(encoding='utf-8')


class MediaFilterTests(unittest.TestCase):


    @unittest.skipUnless(shutil.which('node'), 'Node.js required for live JavaScript classification test')
    def test_actual_javascript_media_classification_and_intersections(self):
        # Evaluate real frontend functions, not a second Python implementation.
        # The test only extracts independently executable functions from app.js.
        def between(start, end):
            return APP.split(start, 1)[1].split(end, 1)[0]

        src = (
            "const safeUrl = " + between('  const safeUrl = ', '  const normalize = ') +
            "const normalize = " + between('  const normalize = ', '  const initials = ') +
            'function youtubeId(link) {' + between('  function youtubeId(link) {', '  function placeholder(p) {') +
            'function projectPlatforms(project) {' + between('  function projectPlatforms(project) {', '  function syncQuery() {')
        )
        fixtures = [
            dict(id='shot', title='Screenshot', platform='PS1', status='Released', screenshots=['/shot.png']),
            dict(id='video', title='Video', platform='PS1', status='Released', youtube_urls=['https://youtu.be/abcdefghijk']),
            dict(id='both', title='Both', platform='PS2', status='Paused', screenshots=['https://x.example/shot.jpg'],
                 youtube_videos=[{'url': 'https://www.youtube.com/watch?v=123456789AB', 'title': 'Trailer'}]),
            dict(id='none', title='None', platform='PS1', status='In-Progress', screenshots=[], youtube_urls=['invalid']),
            dict(id='igdb', title='IGDB only', platform='PS1', status='Released', cover_url='https://x.example/cover.jpg',
                 cover_source='igdb', screenshots=['javascript:alert(1)']),
            dict(id='cover', title='Repo cover', platform='PS1', status='Released', cover_url='https://x.example/cover.jpg',
                 cover_source='repository'),
        ]
        for project in fixtures:
            project['platforms'] = [project['platform']]
        payload = json.dumps(fixtures)
        js = f'''const vm = require('node:vm');
const context = {{ URL, location: {{href:'https://catalog.example/index.html'}},
  state:{{projects:{payload}, search:'',platform:'all',status:'all',media:'all',sort:'az'}} }};
vm.createContext(context);
vm.runInContext({json.dumps(src)}, context);
const categories = context.state.projects.map(p => [p.id,vm.runInContext('mediaCategory',context)(p)]);
const results = {{}};
for (const media of ['all','screenshots','videos','both','none']) {{
  context.state.media = media;
  results[media] = vm.runInContext('filteredProjects',context)().map(p=>p.id).sort();
}}
context.state.media = 'both'; context.state.platform = 'PS2'; context.state.status = 'Paused';
results.intersection = vm.runInContext('filteredProjects',context)().map(p=>p.id);
console.log(JSON.stringify({{categories:Object.fromEntries(categories),results}}));'''
        response = subprocess.run(['node', '-e', js], text=True, capture_output=True, check=True)
        result = json.loads(response.stdout)
        self.assertEqual(result['categories'], {'shot':'screenshots', 'video':'videos',
            'both':'both', 'none':'none', 'igdb':'none', 'cover':'screenshots'})
        self.assertEqual(result['results']['all'], sorted(x['id'] for x in fixtures))
        self.assertEqual(result['results']['screenshots'], ['cover','shot'])
        self.assertEqual(result['results']['videos'], ['video'])
        self.assertEqual(result['results']['both'], ['both'])
        self.assertEqual(result['results']['none'], ['igdb','none'])
        self.assertEqual(result['results']['intersection'], ['both'])


if __name__ == '__main__':
    unittest.main()
