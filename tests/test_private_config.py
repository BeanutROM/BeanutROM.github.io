"""Private repository config must work in both the indexer and watcher."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import build, watch

ROOT = Path(__file__).resolve().parents[1]


class PrivateConfigTests(unittest.TestCase):
    def new_dir(self):
        return tempfile.TemporaryDirectory()

    def test_private_discovery_and_overrides_from_config(self):
        with self.new_dir() as temp:
            p = Path(temp)
            (p / 'config.json').write_text(json.dumps({
                'discovery': {
                    'owners': ['alice', 'team-games'],
                    'include_repositories': ['team-games/special'],
                    'max_projects': 42,
                },
                'overrides': {'team-games/special': {'title': 'A game', 'platforms': ['PS2']}},
            }))
            config = build.load_config({
                'GITHUB_REPOSITORY': 'alice/alice.github.io',
                'CATALOG_PRIVATE_CONFIG_DIR': temp,
            })
            self.assertEqual(config['discovery']['owners'], ['alice', 'team-games'])
            self.assertEqual(config['discovery']['include_repositories'], ['team-games/special'])
            self.assertEqual(config['discovery']['max_projects'], 42)
            self.assertIn('alice/alice.github.io', config['discovery']['exclude_repositories'])
            self.assertEqual(config['overrides']['team-games/special']['title'], 'A game')

    def test_private_files_are_optional(self):
        with self.new_dir() as temp:
            config = build.load_config({'CATALOG_PRIVATE_CONFIG_DIR': temp})
            self.assertEqual(config['discovery']['owners'], [])
            self.assertEqual(config['overrides'], {})
            site = build.load_site_settings(config, {'CATALOG_PRIVATE_CONFIG_DIR': temp})
            self.assertEqual(site['name'], 'Game Catalog')
            self.assertIn('Other', build.load_platform_colors({'CATALOG_PRIVATE_CONFIG_DIR': temp}))


    def test_invalid_json_is_rejected(self):
        with self.new_dir() as temp:
            (Path(temp)/'config.json').write_text('{oops')
            with self.assertRaisesRegex(ValueError, 'config.json'):
                build.load_config({'CATALOG_PRIVATE_CONFIG_DIR': temp})

    def test_invalid_discovery_key_is_rejected(self):
        with self.new_dir() as temp:
            (Path(temp)/'config.json').write_text('{"discovery":{"bad_field": 1}}')
            with self.assertRaisesRegex(ValueError, 'Unknown private config.json discovery keys'):
                build.load_config({'CATALOG_PRIVATE_CONFIG_DIR': temp})

    def test_invalid_discovery_owners_shape_is_rejected(self):
        with self.new_dir() as temp:
            (Path(temp)/'config.json').write_text('{"discovery":{"owners": "alice"}}')
            with self.assertRaisesRegex(ValueError, 'owners must be an array'):
                build.load_config({'CATALOG_PRIVATE_CONFIG_DIR': temp})

    def test_invalid_overrides_shape_is_rejected(self):
        with self.new_dir() as temp:
            (Path(temp)/'config.json').write_text('{"overrides":{"alice/game": "bad"}}')
            with self.assertRaisesRegex(ValueError, 'config.json overrides'):
                build.load_config({'CATALOG_PRIVATE_CONFIG_DIR': temp})

    def test_missing_private_directory_is_error(self):
        with self.new_dir() as temp:
            with self.assertRaisesRegex(ValueError, 'does not exist'):
                build.load_config({'CATALOG_PRIVATE_CONFIG_DIR': str(Path(temp)/'missing')})

    def test_scheduled_watcher_uses_private_discovery(self):
        with self.new_dir() as temp:
            (Path(temp)/'config.json').write_text('{"discovery":{"owners": ["special-team"]}}')
            env = {'GITHUB_EVENT_NAME': 'schedule', 'CATALOG_PRIVATE_CONFIG_DIR': temp,
                   'GITHUB_REPOSITORY': 'sample/sample.github.io'}
            with patch.dict('os.environ', env, clear=True):
                private_hash = build.private_config_fingerprint()
            with patch.dict('os.environ', env, clear=True), \
                 patch.object(watch, 'fetch_snapshot', return_value={'schema_version': 1, 'private_config_hash': private_hash, 'repositories': {}, 'youtube': {}}), \
                 patch.object(watch, 'check_changes', return_value=[]) as check, \
                 patch.object(watch, 'write_step_output'), \
                 patch.object(watch, 'GitHubAPI'):
                watch.main()
            self.assertEqual(check.call_args.args[0]['discovery']['owners'], ['special-team'])


    def test_private_files_trigger_rebuild_when_changed(self):
        with self.new_dir() as temp:
            (Path(temp)/'config.json').write_text('{"overrides":{"sample/game":{"title":"A"}}}')
            env = {'GITHUB_EVENT_NAME': 'schedule', 'CATALOG_PRIVATE_CONFIG_DIR': temp,
                   'GITHUB_REPOSITORY': 'sample/sample.github.io'}
            with patch.dict('os.environ', env, clear=True):
                initial_hash = build.private_config_fingerprint()
                self.assertEqual(len(initial_hash), 64)
                self.assertNotIn('sample/game', initial_hash)
                (Path(temp)/'config.json').write_text('{"overrides":{"sample/game":{"title":"B"}}}')
                next_hash = build.private_config_fingerprint()
                self.assertNotEqual(initial_hash, next_hash)
                baseline = {'schema_version': 1, 'private_config_hash': initial_hash,
                            'repositories': {}, 'youtube': {}}
                with patch.object(watch, 'fetch_snapshot', return_value=baseline), \
                     patch.object(watch, 'check_changes', side_effect=AssertionError('should not poll')), \
                     patch.object(watch, 'write_step_output') as output:
                    watch.main()
                self.assertEqual(output.call_args.args[0], True)
                self.assertIn('Private configuration changed', output.call_args.args[1])

    def test_private_settings_not_published_into_snapshot(self):
        with self.new_dir() as temp:
            (Path(temp)/'config.json').write_text('{"discovery":{"owners":["private-owner-placeholder"]}}')
            with patch.dict('os.environ', {'CATALOG_PRIVATE_CONFIG_DIR': temp}, clear=True):
                snapshot = watch.build_snapshot([], [], {'status':'disabled'})
            self.assertNotIn('private-owner-placeholder', json.dumps(snapshot))
            self.assertRegex(snapshot['private_config_hash'], r'^[0-9a-f]{64}$')

    def test_private_config_overrides_operational_values_without_dropping_defaults(self):
        with self.new_dir() as temp:
            (Path(temp)/'config.json').write_text(json.dumps({
                'updates': {'flags': 7},
                'youtube': {'max_per_game': 9},
                'overrides': {'demo/game': {'title': 'Customized'}},
            }))
            cfg = build.load_config({'CATALOG_PRIVATE_CONFIG_DIR': temp})
            self.assertEqual(cfg['updates']['flags'], 7)
            self.assertTrue(cfg['youtube']['enabled'])
            self.assertEqual(cfg['youtube']['max_per_game'], 9)
            self.assertEqual(cfg['overrides']['demo/game']['title'], 'Customized')
            self.assertEqual(cfg['discovery']['include_all_owner_repos'], True)

    def test_site_settings_cannot_be_supplied_in_config_json(self):
        with self.new_dir() as temp:
            (Path(temp)/'config.json').write_text('{"site":{"discord_url":"https://discord.gg/old"}}')
            with self.assertRaisesRegex(ValueError, 'Unknown private config.json sections'):
                build.load_config({'CATALOG_PRIVATE_CONFIG_DIR': temp})

    def test_private_config_rejects_unknown_section(self):
        with self.new_dir() as temp:
            (Path(temp)/'config.json').write_text('{"not_a_setting": {}}')
            with self.assertRaisesRegex(ValueError, 'Unknown private config.json sections'):
                build.load_config({'CATALOG_PRIVATE_CONFIG_DIR': temp})

    def test_public_icon_is_used_without_private_artwork(self):
        settings = build.load_site_settings({'site': {}}, {})
        self.assertEqual(settings['logo_url'], 'assets/default-icon.svg')
        self.assertEqual(settings['favicon_url'], 'assets/default-icon.svg')
        self.assertTrue((ROOT/'site/assets/default-icon.svg').is_file())

    def test_public_config_is_generic(self):
        config = json.loads((ROOT/'config.json').read_text())
        self.assertEqual(config['discovery']['owners'], [])
        self.assertEqual(config['overrides'], {})
        self.assertNotIn('site', config)
        self.assertEqual(config['updates']['flags'], 3)


if __name__ == '__main__':
    unittest.main()
