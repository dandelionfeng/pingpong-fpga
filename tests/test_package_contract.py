from pathlib import Path
from unittest import TestCase
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'app/pc'));sys.path.insert(0,str(ROOT/'tools'))
import field_actions,launcher
class PackageContract(TestCase):
    def test_remote_original_ids_resolve_to_exhibition_aliases(self):
        for original,local in [('serve_03','serve_01'),('serve_05','serve_02'),('serve_06','serve_03'),('serve_07','serve_04'),('serve_10','serve_05'),('serve_15','serve_06')]:
            self.assertEqual(field_actions.resolve_recording_name(original),local)
    def test_unretained_remote_id_does_not_reuse_a_different_local_record(self):
        self.assertEqual(field_actions.resolve_recording_name('serve_01'),'rk_serve_01')
        self.assertEqual(field_actions.resolve_recording_name('serve_16'),'serve_16')
    def test_recording_path_traversal_rejected(self):
        for name in ['../serve_01','serve/01','C:\\data','']:
            with self.assertRaises(ValueError):field_actions.resolve_recording_name(name)
    def test_launcher_source_resolves_its_own_installation(self):
        self.assertEqual(launcher.installation_root(),ROOT)
    def test_selected_record_quality_flags_are_preserved(self):
        rows=json.loads((ROOT/'docs/test-results.json').read_text('utf-8'))['recordings']
        self.assertEqual(len(rows),6);self.assertEqual(rows[-1]['original'],'serve_15');self.assertTrue(rows[-1]['measurement_estimated'])
        self.assertTrue(all(r['raw_results_unchanged'] for r in rows))


class RetrievalIdentityContract(TestCase):
    def setUp(self):
        import tempfile
        from unittest.mock import patch
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.data=self.root/'data';self.data.mkdir()
        (self.data/'index.json').write_text(json.dumps({'renumbering':[{'original_case':'serve_03','case':'serve_01'}]}),encoding='utf-8')
        self.remote=self.root/'remote';self.pulls=[]
        self.addCleanup(patch.stopall)
        patch.object(field_actions,'CASE_ROOT',self.data).start()
        patch.object(field_actions,'shell',side_effect=self.remote_shell).start()
        patch.object(field_actions,'logged',side_effect=self.logged).start()
        patch.object(field_actions,'log_path',side_effect=lambda label:self.root/(label+'.log')).start()
        patch.object(field_actions.subprocess,'run',return_value=type('Result',(),{'returncode':1})()).start()
        patch('pull_recording.prepare_replay',side_effect=lambda case:case/'app-run-receipt.json').start()
    def make_case(self,path,marker):
        import hashlib
        (path/'input/images').mkdir(parents=True,exist_ok=True)
        blob=marker.encode();(path/'input/images/000.jpg').write_bytes(blob)
        values={'version.json':{'version':field_actions.VERSION['version']},
          'summary.json':{'status':'passed','pairs':1,'marker':marker},
          'measurement-complete.json':{'status':'measured','fit_valid':True,'measurement_estimated':False},
          'input/manifest.json':{'frames':[{'pair_id':1,'file':'images/000.jpg','sha256':hashlib.sha256(blob).hexdigest()}]}}
        for name,value in values.items():(path/name).write_text(json.dumps(value),encoding='utf-8')
    def remote_shell(self,command,*args,**kwargs):
        self.assertEqual(command[0],'sha256sum')
        lines=[field_actions.sha(self.remote/name)+'  '+command[i+1] for i,name in enumerate(['measurement-complete.json','summary.json','input/manifest.json'])]
        return type('Result',(),{'stdout':('\n'.join(lines)+'\n').encode()})()
    def logged(self,command,*args,**kwargs):
        import shutil
        if len(command)>2 and command[-3]=='pull':
            self.pulls.append(command);shutil.copytree(self.remote,Path(command[-1]));return
        # Replay subprocess is outside the scope of these transfer/cache tests.
        case=Path(command[-1]).parent;out=case/'replay';out.mkdir(exist_ok=True)
        (out/'回放.html').write_text('generated',encoding='utf-8')
    def test_sample_alias_does_not_block_new_board_record(self):
        sample=self.data/'serve_01';sample.mkdir();(sample/'sentinel.txt').write_text('bundled sample')
        self.make_case(self.remote,'new board recording')
        page=field_actions.retrieve('serve_03')
        self.assertTrue(page.is_file());self.assertEqual(page.parents[1].name,'rk_serve_03')
        self.assertEqual((sample/'sentinel.txt').read_text(),'bundled sample');self.assertEqual(len(self.pulls),1)
    def test_changed_remote_is_retrieved_and_old_cache_preserved(self):
        self.make_case(self.data/'serve_16','old');self.make_case(self.remote,'new')
        field_actions.retrieve('serve_16')
        self.assertEqual(field_actions.read(self.data/'serve_16/summary.json')['marker'],'new')
        histories=list((self.data/'.history').glob('serve_16-*'));self.assertEqual(len(histories),1)
        self.assertEqual(field_actions.read(histories[0]/'summary.json')['marker'],'old')
        field_actions.retrieve('serve_16');self.assertEqual(len(self.pulls),1)
    def test_incomplete_remote_pull_preserves_existing_record(self):
        self.make_case(self.data/'serve_16','old');self.make_case(self.remote,'new')
        (self.remote/'input/images/000.jpg').write_bytes(b'corrupted')
        with self.assertRaises(ValueError):field_actions.retrieve('serve_16')
        self.assertEqual(field_actions.read(self.data/'serve_16/summary.json')['marker'],'old')
        self.assertFalse((self.data/'.history').exists())


class ReplayPointerContract(TestCase):
    def test_index_html_is_usable_without_a_saved_pointer(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);case=root/'serve_02';(case/'replay').mkdir(parents=True)
            (case/'measurement-complete.json').write_text('{}',encoding='utf-8')
            page=case/'replay/index.html';page.write_text('saved replay',encoding='utf-8')
            with patch.object(field_actions,'CASE_ROOT',root):
                self.assertEqual(field_actions.latest_path(),page.resolve())
                self.assertTrue((root/'latest-replay.txt').is_file())
