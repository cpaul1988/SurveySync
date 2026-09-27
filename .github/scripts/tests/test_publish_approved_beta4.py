"""Offline publication regressions using real approved bytes and a fake gh boundary.

Run after downloading the pinned artifact to approved-beta4. All subprocess
calls are intercepted: tests never publish, upload, change tags, or touch feeds.
The fake REST endpoint deliberately returns 404 for unpublished by-tag lookups.
"""
import base64
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HELPER = Path(__file__).resolve().parents[1] / 'publish_approved_beta4.py'
spec = importlib.util.spec_from_file_location('beta4_publisher', HELPER)
pub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pub)
FIXTURE = Path(__file__).resolve().parents[3] / 'approved-beta4'


class FakeGitHub:
    def __init__(self, files):
        self.files = files
        self.release = None
        self.tag = None
        self.uploaded = {}
        self.feed = {'product': 'SurveySync', 'channels': {
            'beta': {'version': '9.3.2', 'release_tag': 'v9.3.2-beta.4'},
            'stable': {'version': '9.3.2', 'sentinel': 'Do not modify Stable'},
            'developer': {'version': '9.2.6', 'sentinel': ['preserve', 123]},
        }}
        self.feed_sha = 'feed-sha-0'
        self.calls = []
        self.mutations = []
        self.list_prefix = []
        self.duplicate = False
        self.failed_run = False
        self.expired = False
        self.bad_digest = False
        self.conflict = False
        self.forbidden = False

    def make_release(self, draft=True, crlf=False):
        notes = self.files['RELEASE_NOTES_v9_4_0.md'].decode('utf-8-sig')
        notes = pub.normalized_notes(notes)
        if crlf:
            notes = notes.replace('\n', '\r\n')
        self.release = {'id': 397517207, 'tag_name': pub.TAG, 'prerelease': True,
                        'draft': draft, 'body': notes, 'assets': [],
                        'published_at': None if draft else '2026-09-27T05:15:00Z'}
        self.tag = {'object': {'type': 'commit', 'sha': pub.SHA}}

    def snapshot(self):
        result = copy.deepcopy(self.release)
        if result:
            result['assets'] = [{'name': name} for name in self.uploaded]
        return result

    def __call__(self, argv, **kwargs):
        assert argv[0] == 'gh', argv
        args = argv[1:]
        self.calls.append(tuple(args))
        if self.forbidden:
            return subprocess.CompletedProcess(argv, 1, '', 'gh: Forbidden (HTTP 403)')
        def output(data=None, status=0, err=''):
            return subprocess.CompletedProcess(argv, status,
                '' if data is None else json.dumps(data), err)
        if args[0] == 'api':
            path, method = args[1], args[args.index('--method') + 1]
            body = json.loads(kwargs['input']) if kwargs.get('input') is not None else None
            if path == f'{pub.ROOT}/releases/tags/{pub.TAG}':
                if self.release is None or self.release['draft']:
                    return output(status=1, err='gh: Not Found (HTTP 404)')
                return output(self.snapshot())
            if path.startswith(f'{pub.ROOT}/releases?'):
                assert method == 'GET'
                page = int(path.rsplit('=', 1)[1])
                releases = copy.deepcopy(self.list_prefix)
                if self.release:
                    releases.append(self.snapshot())
                    if self.duplicate:
                        releases.append({**self.snapshot(), 'id': 999})
                return output(releases[(page-1)*100:page*100])
            if path.startswith(f'{pub.ROOT}/actions/runs/'):
                run_id = int(path.rsplit('/', 1)[1])
                assert run_id in (pub.RUN, pub.QUALITY_RUN)
                workflow = 'ui-validation.yml' if run_id == pub.RUN else 'quality.yml'
                return output({'status': 'completed',
                    'conclusion': 'failure' if self.failed_run else 'success',
                    'head_sha': pub.SHA, 'head_branch': pub.BRANCH,
                    'path': '.github/workflows/' + workflow,
                    'repository': {'full_name': pub.REPO}})
            if path == f'{pub.ROOT}/actions/artifacts/{pub.ARTIFACT}':
                return output({'expired': self.expired, 'name': 'SurveySync_Beta4_Installer',
                    'digest': 'bad' if self.bad_digest else 'sha256:' + pub.ARCHIVE_HASH,
                    'workflow_run': {'id': pub.RUN, 'head_sha': pub.SHA}})
            if path == f'{pub.ROOT}/git/ref/tags/{pub.TAG}':
                if not self.tag:
                    return output(status=1, err='gh: Not Found (HTTP 404)')
                return output(self.tag)
            if path == f'{pub.ROOT}/git/refs' and method == 'POST':
                assert self.tag is None
                assert body == {'ref': 'refs/tags/' + pub.TAG, 'sha': pub.SHA}
                self.tag = {'object': {'type': 'commit', 'sha': pub.SHA}}
                self.mutations.append('create-tag')
                return output(self.tag)
            if path == f'{pub.ROOT}/releases' and method == 'POST':
                assert self.release is None, 'Duplicate draft creation!'
                assert body['tag_name'] == pub.TAG and body['target_commitish'] == pub.SHA
                assert body['draft'] is True and body['prerelease'] is True
                assert body['make_latest'] == 'false'
                self.make_release()
                self.release['body'] = body['body']
                self.mutations.append('create-draft')
                return output(self.snapshot())
            if self.release and path == f'{pub.ROOT}/releases/{self.release["id"]}':
                if method == 'PATCH':
                    assert body == {'draft': False, 'prerelease': True, 'make_latest': 'false'}
                    assert set(self.uploaded) == set(pub.EXPECTED)
                    self.release['draft'] = False
                    self.release['published_at'] = '2026-09-27T05:15:00Z'
                    self.mutations.append('publish-by-id')
                else:
                    assert method == 'GET'
                return output(self.snapshot())
            if path == f'{pub.ROOT}/contents/update.json?ref=main':
                return output({'encoding': 'base64', 'sha': self.feed_sha,
                    'content': base64.b64encode(json.dumps(self.feed).encode()).decode()})
            if path == f'{pub.ROOT}/contents/update.json' and method == 'PUT':
                assert body['branch'] == 'main' and body['sha'] == self.feed_sha
                if self.conflict:
                    return output(status=1, err='gh: Conflict (HTTP 409)')
                self.feed = json.loads(base64.b64decode(body['content']))
                self.feed_sha = 'feed-sha-next'
                self.mutations.append('update-beta-feed')
                return output({'content': {'sha': self.feed_sha}})
            raise AssertionError(('Unexpected API request', path, method, body))
        assert args[0] == 'release' and args[2] == pub.TAG, args
        assert args[args.index('--repo')+1] == pub.REPO
        if args[1] == 'upload':
            assert self.release and self.release['draft'] and '--clobber' not in args
            for name in args[3:args.index('--repo')]:
                path = Path(name)
                assert path.name not in self.uploaded, 'Existing asset overwritten!'
                self.uploaded[path.name] = path.read_bytes()
                self.mutations.append('upload:' + path.name)
            return output()
        if args[1] == 'download':
            name = args[args.index('--pattern')+1]
            (Path(args[args.index('--dir')+1]) / name).write_bytes(self.uploaded[name])
            return output()
        raise AssertionError(('Unexpected release command', args))


class PublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = {}
        for name, digest in pub.EXPECTED.items():
            paths = list(FIXTURE.rglob(name))
            if len(paths) != 1:
                raise AssertionError(f'Download the approved artifact to {FIXTURE} first: {name}')
            raw = paths[0].read_bytes()
            if hashlib.sha256(raw).hexdigest() != digest:
                raise AssertionError('Test fixture is not the pinned approved artifact: ' + name)
            cls.files[name] = raw

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path.cwd()
        self.addCleanup(os.chdir, self.cwd)
        os.chdir(self.temp.name)
        folder = Path('approved-beta4')
        folder.mkdir()
        for name, raw in self.files.items():
            (folder/name).write_bytes(raw)
        self.fake = FakeGitHub(self.files)
        env = {'GITHUB_REPOSITORY': pub.REPO, 'GITHUB_REF': 'refs/heads/' + pub.BRANCH,
               'GITHUB_EVENT_NAME': 'workflow_dispatch', 'RELEASE_VERSION': '9.4.0',
               'BETA_SUFFIX': 'beta.4', 'GITHUB_STEP_SUMMARY': str(Path('summary.md').resolve())}
        self.enterContext(patch.dict(os.environ, env))
        self.enterContext(patch.object(pub.subprocess, 'run', side_effect=self.fake))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.other = copy.deepcopy({k:v for k,v in self.fake.feed['channels'].items() if k != 'beta'})

    def published(self):
        self.assertFalse(self.fake.release['draft'])
        self.assertEqual(self.fake.feed['channels']['beta']['sha256'], pub.EXPECTED['SurveySync_Setup_9.4.0.exe'])
        self.assertEqual(self.fake.feed['channels']['beta']['release_tag'], pub.TAG)
        self.assertEqual({k:v for k,v in self.fake.feed['channels'].items() if k != 'beta'}, self.other)
        self.assertEqual(self.fake.uploaded, self.files)
        self.assertNotIn(('api', f'{pub.ROOT}/releases/tags/{pub.TAG}', '--method', 'GET'), self.fake.calls)

    def test_new_draft_uses_numeric_id_not_published_only_tag_endpoint(self):
        pub.main()
        self.published()
        self.assertEqual(self.fake.mutations.count('create-draft'), 1)
        self.assertEqual(self.fake.mutations.count('publish-by-id'), 1)

    def test_run23_existing_empty_draft_and_windows_crlf_resume(self):
        self.fake.make_release(crlf=True)
        self.assertIn('\r\n', self.fake.release['body'])
        pub.main()
        self.published()
        self.assertNotIn('create-draft', self.fake.mutations)
        self.assertNotIn('create-tag', self.fake.mutations)

    def test_transport_reproduces_draft_404_but_listing_finds_it(self):
        self.fake.make_release()
        self.assertIsNone(pub.api(f'{pub.ROOT}/releases/tags/{pub.TAG}', optional=True))
        self.assertEqual(pub.find_release()['id'], 397517207)

    def test_partial_draft_reuses_existing_assets_without_overwrite(self):
        self.fake.make_release()
        name = 'SurveySync_Setup_9.4.0.exe'
        self.fake.uploaded[name] = self.files[name]
        pub.main()
        self.published()
        self.assertNotIn('upload:' + name, self.fake.mutations)

    def test_published_retry_is_idempotent(self):
        pub.main()
        self.fake.mutations.clear()
        pub.main()
        self.published()
        self.assertEqual(self.fake.mutations, [])

    def test_published_but_missing_asset_fails_closed(self):
        self.fake.make_release(draft=False)
        with self.assertRaisesRegex(RuntimeError, 'Published release is incomplete'):
            pub.main()
        self.assertEqual(self.fake.mutations, [])

    def test_pagination_recovers_draft_beyond_first_page(self):
        self.fake.make_release()
        self.fake.list_prefix = [{'tag_name': f'other-{i}', 'id': i+1} for i in range(100)]
        pub.main()
        self.published()
        self.assertIn(('api', f'{pub.ROOT}/releases?per_page=100&page=2', '--method', 'GET'), self.fake.calls)

    def test_duplicate_release_refused(self):
        self.fake.make_release()
        self.fake.duplicate = True
        with self.assertRaisesRegex(RuntimeError, 'Multiple releases'):
            pub.main()
        self.assertEqual(self.fake.mutations, [])

    def test_conflicting_tag_is_not_moved(self):
        self.fake.make_release()
        self.fake.tag['object']['sha'] = '0' * 40
        with self.assertRaisesRegex(RuntimeError, 'No tag will be moved'):
            pub.main()
        self.assertEqual(self.fake.mutations, [])

    def test_different_notes_are_not_silently_normalized_away(self):
        self.fake.make_release(crlf=True)
        self.fake.release['body'] += '\r\nDifferent content'
        with self.assertRaisesRegex(RuntimeError, 'notes differ'):
            pub.main()
        self.assertEqual(self.fake.mutations, [])

    def test_local_corruption_prevents_mutations(self):
        Path('approved-beta4/SurveySync_Setup_9.4.0.exe').write_bytes(b'MZcorrupt')
        with self.assertRaisesRegex(RuntimeError, 'Integrity mismatch'):
            pub.main()
        self.assertEqual(self.fake.mutations, [])

    def test_remote_corruption_blocks_publication_and_feed(self):
        self.fake.make_release()
        self.fake.uploaded = dict(self.files)
        self.fake.uploaded['SurveySync_Setup_9.4.0.exe'] = b'MZcorrupt'
        with self.assertRaisesRegex(RuntimeError, 'Integrity mismatch'):
            pub.main()
        self.assertTrue(self.fake.release['draft'])
        self.assertEqual(self.fake.mutations, [])

    def test_failed_approved_ci_blocks_mutations(self):
        self.fake.failed_run = True
        with self.assertRaisesRegex(RuntimeError, 'not a successful check'):
            pub.main()
        self.assertEqual(self.fake.mutations, [])

    def test_expired_artifact_blocks_mutations(self):
        self.fake.expired = True
        with self.assertRaisesRegex(RuntimeError, 'artifact provenance'):
            pub.main()
        self.assertEqual(self.fake.mutations, [])

    def test_wrong_archive_digest_blocks_mutations(self):
        self.fake.bad_digest = True
        with self.assertRaisesRegex(RuntimeError, 'artifact provenance'):
            pub.main()
        self.assertEqual(self.fake.mutations, [])

    def test_newer_beta_suffix_not_downgraded(self):
        self.fake.feed['channels']['beta'] = {'version': '9.4.0', 'release_tag': 'v9.4.0-beta.5'}
        with self.assertRaisesRegex(RuntimeError, 'later 9.4.0 beta'):
            pub.main()
        self.assertEqual(self.fake.mutations, [])

    def test_newer_version_not_downgraded(self):
        self.fake.feed['channels']['beta'] = {'version': '9.5.0'}
        with self.assertRaisesRegex(RuntimeError, 'newer beta'):
            pub.main()
        self.assertEqual(self.fake.mutations, [])

    def test_wrong_branch_blocks_every_remote_call(self):
        os.environ['GITHUB_REF'] = 'refs/heads/main'
        with self.assertRaisesRegex(RuntimeError, 'candidate branch'):
            pub.main()
        self.assertEqual(self.fake.calls, [])

    def test_permission_failure_is_not_treated_as_missing_release(self):
        self.fake.forbidden = True
        with self.assertRaisesRegex(RuntimeError, 'HTTP 403'):
            pub.find_release()
        self.assertEqual(self.fake.mutations, [])

    def test_feed_conflict_can_resume_without_republishing_or_overwriting(self):
        self.fake.make_release(crlf=True)
        self.fake.conflict = True
        with self.assertRaisesRegex(RuntimeError, 'HTTP 409'):
            pub.main()
        self.assertFalse(self.fake.release['draft'])
        self.assertEqual(self.fake.feed['channels']['beta']['version'], '9.3.2')
        self.fake.conflict = False
        self.fake.mutations.clear()
        pub.main()
        self.published()
        self.assertEqual(self.fake.mutations, ['update-beta-feed'])


if __name__ == '__main__':
    unittest.main()
