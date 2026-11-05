"""About page is blank by default and is populated only from private about.md."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build, watch

ROOT = Path(__file__).resolve().parents[1]


class AboutPageTests(unittest.TestCase):
    def make_page(self, work):
        page = Path(work) / 'about.html'
        page.write_text((ROOT / 'site' / 'about.html').read_text(encoding='utf-8'), encoding='utf-8')
        return page

    def article(self, html):
        return html.split(build.ABOUT_START, 1)[1].split(build.ABOUT_END, 1)[0]


    def test_default_page_is_truly_blank_and_accessible(self):
        html = (ROOT / 'site/about.html').read_text(encoding='utf-8')
        self.assertFalse(self.article(html).strip())
        self.assertIn('id="about-content"', html)
        self.assertIn('Skip to About', html)
        with tempfile.TemporaryDirectory() as tmp:
            page = self.make_page(tmp)
            self.assertFalse(build.render_about_page(env={}, output_path=page))
            self.assertFalse(self.article(page.read_text()).strip())

    def test_private_markdown_rendered_as_html_with_gfm_features(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            private = parent / 'private'
            private.mkdir()
            (private / 'about.md').write_text('''# About us

Welcome to **this project**. Read [the guide](https://example.com/help).

| Game | Platform |
|---|---|
| Athena | PS1 |

- [x] Complete
- [ ] In progress

~~Old text~~

```python
print("hi")
```
''', encoding='utf-8')
            page = self.make_page(tmp)
            self.assertTrue(build.render_about_page(
                env={'CATALOG_PRIVATE_CONFIG_DIR': str(private)}, output_path=page))
            contents = self.article(page.read_text())
            for expected in ('<h1>About us</h1>', '<strong>this project</strong>', '<table>',
                             '<td>Athena</td>', 'href="https://example.com/help"',
                             'type="checkbox"', '<del>Old text</del>', '<pre><code', 'print('):
                self.assertIn(expected, contents)
            self.assertNotIn('about.md', contents)

    def test_missing_or_deleted_markdown_clears_previously_rendered_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            private.mkdir()
            markdown = private / 'about.md'
            markdown.write_text('# OLD COPY', encoding='utf-8')
            page = self.make_page(tmp)
            env = {'CATALOG_PRIVATE_CONFIG_DIR': str(private)}
            self.assertTrue(build.render_about_page(env=env, output_path=page))
            self.assertIn('OLD COPY', self.article(page.read_text()))
            markdown.write_text('  \n', encoding='utf-8')
            self.assertFalse(build.render_about_page(env=env, output_path=page))
            self.assertFalse(self.article(page.read_text()).strip())
            markdown.write_text('# NEW COPY', encoding='utf-8')
            self.assertTrue(build.render_about_page(env=env, output_path=page))
            markdown.unlink()
            self.assertFalse(build.render_about_page(env=env, output_path=page))
            self.assertFalse(self.article(page.read_text()).strip())

    def test_raw_html_and_script_urls_do_not_execute(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            private.mkdir()
            (private / 'about.md').write_text(
                '<script>alert(1)</script>\n\n<img src=x onerror=alert(2)>\n\n'
                '[bad](javascript:alert(3))\n\n![bad](javascript:alert(4))', encoding='utf-8')
            page = self.make_page(tmp)
            self.assertTrue(build.render_about_page(
                env={'CATALOG_PRIVATE_CONFIG_DIR': str(private)}, output_path=page))
            content = self.article(page.read_text())
            self.assertNotIn('<script', content)
            self.assertNotIn('<img src=x onerror', content)
            self.assertNotIn('href="javascript:', content)
            self.assertNotIn('src="javascript:', content)
            self.assertIn('&lt;script&gt;', content)
            self.assertIn('#harmful-link', content)

    def test_markdown_change_triggers_watcher_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / 'private'
            private.mkdir()
            env = {'CATALOG_PRIVATE_CONFIG_DIR': str(private),
                   'GITHUB_EVENT_NAME':'schedule', 'GITHUB_REPOSITORY':'sample/sample.github.io'}
            with patch.dict('os.environ', env, clear=True):
                old_hash = build.private_config_fingerprint()
                (private / 'about.md').write_text('# New About', encoding='utf-8')
                updated_hash = build.private_config_fingerprint()
                self.assertNotEqual(old_hash, updated_hash)
                baseline = {'schema_version': 1, 'private_config_hash': old_hash,
                            'repositories': {}, 'youtube': {}}
                with patch.object(watch, 'fetch_snapshot', return_value=baseline), \
                     patch.object(watch, 'check_changes', side_effect=AssertionError('no poll')), \
                     patch.object(watch, 'write_step_output') as output:
                    watch.main()
                self.assertEqual(output.call_args.args[0], True)
                self.assertIn('Private configuration changed', output.call_args.args[1])

    def test_full_catalog_build_writes_private_about_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            private = work / 'private'
            private.mkdir()
            (private / 'about.md').write_text('# Published About\n\nPrivate Markdown becomes public.', encoding='utf-8')
            page = self.make_page(tmp)
            output = work / 'site/data/projects.json'
            env = {'CATALOG_PRIVATE_CONFIG_DIR': str(private)}
            with patch.dict('os.environ', env, clear=True), \
                 patch.object(build, 'ROOT', work), \
                 patch.object(build, 'OUTPUT', output), \
                 patch.object(build, 'ABOUT_PAGE', page), \
                 patch.object(build, 'discover_repos', return_value=[]), \
                 patch.object(build, 'generate_thumbnails'), \
                 patch.object(build, 'index_youtube', return_value={'status': 'not_configured', 'videos': []}):
                build.main()
            self.assertIn('<h1>Published About</h1>', page.read_text())
            self.assertIn('Private Markdown becomes public.', page.read_text())
            self.assertNotIn('about.md', output.read_text())
            self.assertFalse((work / 'site/about.md').exists())
            self.assertTrue(output.exists())


if __name__ == '__main__':
    unittest.main()
