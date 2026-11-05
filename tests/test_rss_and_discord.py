"""RSS history, update classification, and optional Discord integration."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from scripts import build, rss_feed

ROOT = Path(__file__).resolve().parents[1]


def project(repo='owner/game', status='Released', tag='v1.0', date='2026-10-21T15:00:00Z'):
    return {
        'repo':repo, 'id':repo.lower(), 'title':'Example & Game', 'status':status,
        'has_release':status == 'Released', 'release_tag':tag, 'release_stage': 'Beta' if 'beta' in tag else '',
        'release_published_at':date, 'release_url':'https://github.com/'+repo+'/releases/tag/'+tag,
        'github_url':'https://github.com/'+repo, 'updated_at':date, 'platform':'PS2',
    }


class RSSDiscordTests(unittest.TestCase):
    def make_feed(self, entries, prior=None, prior_projects=None, flags=3):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'feed.xml'
            count=rss_feed.write_rss(entries, {'name':'Test & Games'}, path, 'https://example.github.io',
                      prior, json.dumps({'projects':prior_projects}).encode() if prior_projects is not None else None,
                      flags)
            content=path.read_bytes()
            return count,content,ET.fromstring(content)

    def test_initial_feed_has_release_but_no_initial_status_spam(self):
        release=project()
        beta=project('owner/beta',tag='v2.0-beta.1')
        paused=project('owner/paused',status='Paused',tag='')
        n, xml, root=self.make_feed([release,beta,paused])
        self.assertEqual(n,2)
        self.assertIn(b'Test &amp; Games',xml)
        self.assertEqual(root.tag,'rss')
        self.assertEqual(root.attrib['version'],'2.0')
        self.assertEqual(len(root.findall('./channel/item')),2)
        self.assertIn('Beta release',[e.findtext('category') for e in root.findall('./channel/item')])
        self.assertEqual(root.find('./channel/link').text,'https://example.github.io')
        self.assertEqual(root.find('./channel/{http://www.w3.org/2005/Atom}link').get('href'),
                         'https://example.github.io/feed.xml')
        self.assertEqual(root.find('./channel/item/guid').attrib['isPermaLink'],'false')

    def test_every_published_github_release_is_included_without_extra_api_calls(self):
        from tests.test_build import FakeApi, example
        api = FakeApi(releases=[
            {'draft':False, 'tag_name':'v1.0-alpha', 'published_at':'2026-09-01T12:00:00Z',
             'html_url':'https://github.com/alice/translation/releases/tag/v1.0-alpha'},
            {'draft':False, 'tag_name':'v1.0-beta', 'published_at':'2026-09-02T12:00:00Z',
             'html_url':'https://github.com/alice/translation/releases/tag/v1.0-beta'},
            {'draft':False, 'tag_name':'v1.0', 'published_at':'2026-09-03T12:00:00Z',
             'html_url':'https://github.com/alice/translation/releases/tag/v1.0'},
            {'draft':True, 'tag_name':'v1.1-draft', 'published_at':'2026-09-04T12:00:00Z',
             'html_url':'https://github.com/alice/translation/releases/tag/v1.1-draft'},
        ])
        sink=[]
        result=build.make_project(api,example(),{},release_event_sink=sink)
        self.assertEqual(result['release_tag'],'v1.0')
        self.assertEqual([entry['release_tag'] for entry in sink],
                         ['v1.0-alpha','v1.0-beta','v1.0'])
        self.assertEqual(len([path for path in api.paths if path.endswith('/releases')]),1)
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'feed.xml'
            count=rss_feed.write_rss([result],{'name':'Example'},output,
                         release_history=sink)
            self.assertEqual(count,3)
            content=ET.parse(output)
            self.assertEqual([item.findtext('category') for item in content.findall('./channel/item')],
                             ['Full release','Beta release','Alpha release'])

    def test_unchanged_rebuild_is_idempotent_even_with_previous_feed(self):
        p=project()
        n, old, oldroot=self.make_feed([p])
        n2, new, newroot=self.make_feed([p],old, [p])
        self.assertEqual(n,n2)
        self.assertEqual([x.text for x in oldroot.findall('./channel/item/guid')],
                         [x.text for x in newroot.findall('./channel/item/guid')])
        self.assertEqual(old,new)

    def test_new_release_retains_past_entries_and_reuses_stable_guid(self):
        first=project(tag='v1.0')
        _, prior,_=self.make_feed([first])
        second=project(tag='v1.2-beta.3',date='2026-11-03T10:00:00Z')
        n,_,root=self.make_feed([second],prior,[first])
        self.assertEqual(n,2)
        titles=[e.findtext('title') for e in root.findall('./channel/item')]
        self.assertIn('Example & Game: v1.0 (Full release)',titles)
        self.assertIn('Example & Game: v1.2-beta.3 (Beta release)',titles)
        self.assertIn('Beta release',[e.findtext('category') for e in root.findall('./channel/item')])

    def test_status_transition_appears_once_but_date_only_change_does_not(self):
        before=project(status='In-Progress',tag='',date='2026-10-01T00:00:00Z')
        after=project(status='Paused',tag='',date='2026-11-03T00:00:00Z')
        n,old,root=self.make_feed([after],prior_projects=[before])
        self.assertEqual(n,1)
        self.assertEqual(root.find('./channel/item/category').text,'Status change')
        self.assertIn('In-Progress to Paused',root.find('./channel/item/description').text)
        n,_,root=self.make_feed([after],old,[after])
        self.assertEqual(n,1)
        after['updated_at']='2026-11-04T00:00:00Z'
        n,_,_=self.make_feed([after],old,[after])
        self.assertEqual(n,1)

    def test_flags_control_new_items(self):
        p=project()
        self.assertEqual(self.make_feed([p],flags=2)[0],0)
        self.assertEqual(self.make_feed([p],flags=1)[0],1)
        before=project(status='In-Progress')
        after=project(status='Paused')
        self.assertEqual(self.make_feed([after],prior_projects=[before],flags=1)[0],0)
        self.assertEqual(self.make_feed([after],prior_projects=[before],flags=2)[0],1)

    def test_history_bounded_and_sorted_and_no_duplicate_ids(self):
        releases=[project('owner/g'+str(i),date=f'2026-10-{(i%28)+1:02d}T12:00:00Z') for i in range(150)]
        n,_,root=self.make_feed(releases)
        self.assertEqual(n,100)
        ids=[e.findtext('guid') for e in root.findall('./channel/item')]
        self.assertEqual(len(ids),len(set(ids)))
        stamps=[rss_feed.parse_date(e.findtext('pubDate')) for e in root.findall('./channel/item')]
        self.assertEqual(stamps,sorted(stamps,reverse=True))

    def test_invalid_rss_refused(self):
        with self.assertRaisesRegex(RuntimeError,'invalid XML'):
            self.make_feed([project()],b'<rss><bad')
        with self.assertRaisesRegex(RuntimeError,'not RSS 2.0'):
            self.make_feed([project()],b'<rss version="1.0"/>')

    def test_public_and_private_discord_config_and_header_order(self):
        cfg=json.loads((ROOT/'config.json').read_text())
        self.assertNotIn('site', cfg)
        for name in ('index.html','about.html'):
            text=(ROOT/'site'/name).read_text()
            self.assertLess(text.index('id="nav-discord"'),text.index('id="support-link"'))
            self.assertIn('id="nav-rss"',text)
            self.assertIn('rel="alternate" type="application/rss+xml"',text)
            self.assertIn('aria-label="Join our Discord server"',text)
        for name in ('app.js','about.js'):
            text=(ROOT/'site'/name).read_text()
            self.assertIn("safeUrl(site.discord_url)",text)
            self.assertIn('discord.hidden = !validDiscordInvite',text)
            self.assertIn("host === 'discord.gg'",text)
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp,'branding.json').write_text(json.dumps({'site':{'discord_url':'https://discord.gg/EXAMPLE'}}))
            env={'CATALOG_PRIVATE_CONFIG_DIR':tmp}
            merged=build.load_config(env)
            self.assertEqual(build.load_site_settings(merged,env)['discord_url'],'https://discord.gg/EXAMPLE')

    def test_local_offline_feed_generated_without_external_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(rss_feed,'fetch_published',side_effect=AssertionError('unexpected network')):
                count=rss_feed.build_rss_feed([project()],{'name':'Test'},Path(tmp)/'feed.xml',{},3)
            self.assertEqual(count,1)
            self.assertTrue((Path(tmp)/'feed.xml').exists())

    def test_project_page_canonical_url_and_override(self):
        self.assertEqual(rss_feed.site_address({'GITHUB_REPOSITORY':'Alice/Project'}),
                         'https://alice.github.io/Project')
        self.assertEqual(rss_feed.site_address({'GITHUB_REPOSITORY':'Alice/Alice.github.io'}),
                         'https://alice.github.io')
        self.assertEqual(rss_feed.site_address({'CATALOG_SITE_URL':'https://example.com/site'}),
                         'https://example.com/site')

    def test_workflow_passes_site_url_to_build(self):
        workflow=(ROOT/'.github/workflows/pages.yml').read_text()
        self.assertEqual(workflow.count('CATALOG_SITE_URL: ${{ vars.CATALOG_SITE_URL }}'),2)


if __name__=='__main__':
    unittest.main()
