"""Offline publication state-machine tests; no GitHub writes or real releases."""
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('publish943', Path(__file__).resolve().parents[1]/'publish_verified_943.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def approved():
    files={name: (b'MZapproved fixture' if name.endswith('.exe') else b'approved text\n') for name in m.FILES}
    files['VERSION.txt']=b'9.4.3\n'
    files['RELEASE_ID.txt']=b'9.4.3-beta.1\n'
    return {'version':'9.4.3','publish_stable':True,'source_sha':'a'*40,'base_sha':'b'*40,
            'runs':{'acceptance':1,'quality':2,'ui':3,'remaining':4},'artifact_id':10,'archive_sha256':'c'*64,
            'files':{n:{'size':len(v),'sha256':hashlib.sha256(v).hexdigest()} for n,v in files.items()}},files


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.r,self.files=approved()
        self.feed={'product':'SurveySync','channels':{'stable':{'version':'9.4.0'},'beta':{'version':'9.4.0'},
            'developer':{'version':'9.2.6','sentinel':'keep'}},'unrelated':'retained'}
        self.release=None
        self.merged=False
        self.fail_run=False
        self.moved=False
        self.bad_tag=False
        self.feed_conflict=False
        self.writes=[]
        self.head='d'*40

    def api(self,path,method='GET',body=None,optional=False):
        if method!='GET': self.writes.append((path,method))
        if '/compare/' in path:
            return {'status':'ahead','ahead_by':1,'behind_by':0,'files':[{'filename':m.RECEIPT}]}
        if path.endswith('/git/ref/heads/'+m.BRANCH): return {'object':{'sha':'x'*40 if self.moved else self.head}}
        if '/actions/runs/' in path:
            number=int(path.rsplit('/',1)[1]);key={1:'acceptance',2:'quality',3:'ui',4:'remaining'}[number]
            return {'status':'completed','conclusion':'failure' if self.fail_run else 'success',
                'head_sha':self.r['source_sha'],'head_branch':m.BRANCH,'path':m.WORKFLOWS[key],
                'repository':{'full_name':m.REPO}}
        if '/actions/artifacts/' in path:
            return {'expired':False,'name':'SurveySync_9.4.3_beta1_Verified_Installer','digest':'sha256:'+self.r['archive_sha256'],
                'workflow_run':{'id':1,'head_sha':self.r['source_sha']}}
        if '/contents/update.json' in path:
            if method=='PUT':
                if self.feed_conflict:raise RuntimeError('HTTP 409 optimistic conflict')
                self.feed=json.loads(base64.b64decode(body['content']))
            return {'encoding':'base64','sha':'old-blob','content':base64.b64encode(json.dumps(self.feed).encode()).decode()}
        if path.endswith('/pulls/14'):
            return {'head':{'sha':self.head},'base':{'ref':'main'},'draft':True,'merged':self.merged,'merge_commit_sha':'e'*40}
        if path.endswith('/pulls/14/merge'):
            self.merged=True;return {'merged':True,'sha':'e'*40}
        if path.endswith('/git/ref/heads/main'):return {'object':{'sha':self.r['base_sha']}}
        if '/git/ref/tags/' in path:
            return {'object':{'type':'commit','sha':'f'*40 if self.bad_tag else self.r['source_sha']}}
        if '/releases?' in path:return [] if self.release is None else [self.release]
        if path.endswith('/releases') and method=='POST':
            self.release={**body,'id':99,'assets':[],'published_at':'2026-09-27T00:00:00Z','html_url':'release'}
            return self.release
        if path.endswith('/releases/99') and method=='PATCH':
            self.release.update(body);return self.release
        if path.endswith('/releases/latest'):return self.release
        raise AssertionError((path,method,body))

    def gh(self,*args,**kw):
        if args[:2]==('run','download'):
            folder=Path(args[args.index('--dir')+1]);folder.mkdir(exist_ok=True)
            for n,v in self.files.items():(folder/n).write_bytes(v)
        elif args[:2]==('release','upload'):
            self.release['assets']=[{'name':n} for n in self.files]
        elif args[:2]==('release','download'):
            folder=Path(args[args.index('--dir')+1]);n=args[args.index('--pattern')+1]
            (folder/n).write_bytes(self.files[n])
        elif args[:2]!=('pr','ready'):raise AssertionError(args)
        return ''

    def execute(self):
        (self.root/'.github').mkdir(exist_ok=True)
        (self.root/m.RECEIPT).write_text(json.dumps(self.r))
        old=os.getcwd();os.chdir(self.root)
        try:
            with patch.dict(os.environ,{'GITHUB_REPOSITORY':m.REPO,'GITHUB_REF':'refs/heads/'+m.BRANCH,
                    'GITHUB_EVENT_NAME':'push','GITHUB_SHA':self.head,'GITHUB_STEP_SUMMARY':str(self.root/'summary.md')}), \
                 patch.object(m,'api',side_effect=self.api),patch.object(m,'gh',side_effect=self.gh):
                m.main()
        finally:os.chdir(old)

    def test_complete_draft_publish_feed_and_latest(self):
        self.execute()
        self.assertTrue(self.merged)
        self.assertEqual(self.feed['channels']['stable']['release_id'], '9.4.3-beta.1')
        self.assertFalse(self.release['draft'])
        self.assertFalse(self.release['prerelease'])
        self.assertEqual(self.release['make_latest'],'true')
        self.assertEqual(self.feed['channels']['stable']['version'],'9.4.3')
        self.assertEqual(self.feed['channels']['stable']['sha256'],self.feed['channels']['beta']['sha256'])
        self.assertEqual(self.feed['channels']['developer'],{'version':'9.2.6','sentinel':'keep'})
        self.assertEqual(self.feed['unrelated'],'retained')

    def test_failed_windows_run_prevents_all_writes(self):
        self.fail_run=True
        with self.assertRaisesRegex(RuntimeError,'Windows check'):self.execute()
        self.assertEqual(self.writes,[])

    def test_changed_source_prevents_all_writes(self):
        self.moved=True
        with self.assertRaisesRegex(RuntimeError,'branch moved'):self.execute()
        self.assertEqual(self.writes,[])

    def test_hash_mismatch_prevents_all_writes(self):
        self.r['files']['SurveySync_Setup_9.4.3-beta.1.exe']['sha256']='0'*64
        with self.assertRaisesRegex(RuntimeError,'hash mismatch'):self.execute()
        self.assertEqual(self.writes,[])

    def test_newer_live_version_prevents_all_writes(self):
        self.feed['channels']['stable']['version']='9.5.0'
        with self.assertRaisesRegex(RuntimeError,'downgrade'):self.execute()
        self.assertEqual(self.writes,[])

    def test_conflicting_same_version_prevents_all_writes(self):
        self.feed['channels']['stable']={'version':'9.4.3','sha256':'0'*64,'release_tag':m.TAG}
        with self.assertRaisesRegex(RuntimeError,'Conflicting'):self.execute()
        self.assertEqual(self.writes,[])

    def test_conflicting_tag_never_moves_it(self):
        self.bad_tag=True
        with self.assertRaisesRegex(RuntimeError,'tag conflicts'):self.execute()
        self.assertFalse(any('/git/refs' in p for p,_ in self.writes))
        self.assertIsNone(self.release)

    def test_optimistic_feed_conflict_never_forces(self):
        self.feed_conflict=True
        with self.assertRaisesRegex(RuntimeError,'409'):self.execute()
        self.assertEqual(self.feed['channels']['stable']['version'],'9.4.0')
        self.assertEqual(sum('/contents/update.json' in p for p,_ in self.writes),1)

    def test_receipt_rejects_missing_authorization(self):
        self.r['publish_stable']=False
        with self.assertRaises(RuntimeError):m.validate_receipt(self.r)

    def test_receipt_rejects_missing_test_run(self):
        del self.r['runs']['quality']
        with self.assertRaises(RuntimeError):m.validate_receipt(self.r)

    def test_receipt_rejects_extra_file(self):
        self.r['files']['unexpected.exe']=next(iter(self.r['files'].values()))
        with self.assertRaises(RuntimeError):m.validate_receipt(self.r)

    def test_receipt_rejects_invalid_digests(self):
        for field in ('source_sha','base_sha','archive_sha256'):
            with self.subTest(field=field):
                r=copy.deepcopy(self.r);r[field]='invalid'
                with self.assertRaises(RuntimeError):m.validate_receipt(r)

    def test_receipt_rejects_boolean_run_id(self):
        self.r['runs']['quality']=True
        with self.assertRaises(RuntimeError):m.validate_receipt(self.r)

    def test_release_lookup_uses_authenticated_listing_not_published_tag_endpoint(self):
        with patch.object(m,'api',side_effect=[([{'tag_name':'old'}]*100),[{'tag_name':m.TAG,'draft':True,'id':5}]]) as call:
            self.assertEqual(m.find_release(m.TAG)['id'],5)
            self.assertIn('page=2',call.call_args.args[0])

    def test_missing_file_fails(self):
        with self.assertRaises(RuntimeError):m.verify_file(self.root/'absent.exe',{'size':10,'sha256':'0'*64})

if __name__=='__main__':unittest.main()
