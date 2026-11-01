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
    def test_source_package_has_embedded_runtime_contract(self):
        self.assertEqual(launcher.runtime_mode(ROOT),'source-embedded')
        result=launcher.source_installation(ROOT)
        self.assertEqual(result['mode'],'source-embedded');self.assertFalse(result['full_runtime_present'])
        self.assertEqual(result['reference_case_names'],[f'serve_{i:02}' for i in range(1,7)])
        self.assertEqual(result['recordings_included'],0)
    def test_selected_record_quality_flags_are_preserved(self):
        rows=json.loads((ROOT/'docs/test-results.json').read_text('utf-8'))['recordings']
        self.assertEqual(len(rows),6);self.assertEqual(rows[-1]['original'],'serve_15');self.assertTrue(rows[-1]['measurement_estimated'])
        self.assertTrue(all(r['raw_results_unchanged'] for r in rows))
