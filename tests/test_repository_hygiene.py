import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('check_repo', Path(__file__).resolve().parents[1] / 'tools' / 'check_repo.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

class HygieneTests(unittest.TestCase):
    def test_valid_rtl_and_chinese_doc(self):
        self.assertEqual(checker.inspect_file('fpga/rtl/top.sv', b'module top; endmodule\n'), [])
        self.assertEqual(checker.inspect_file('docs/说明.md', '这是说明。\n---\n'.encode()), [])

    def test_conflict_is_rejected(self):
        content = b'<<<<<<< branch\nold\n=======\nnew\n>>>>>>> main\n'
        self.assertTrue(checker.inspect_file('fpga/rtl/top.v', content))

    def test_token_is_rejected_without_echo(self):
        token = ('gh' + 'p_' + 'x' * 36).encode()
        result = checker.inspect_file('settings.py', token)
        self.assertTrue(result)
        self.assertNotIn(token.decode(), str(result))

    def test_env_and_weights_are_rejected(self):
        self.assertTrue(checker.inspect_file('.env.local', b'example'))
        self.assertTrue(checker.inspect_file('vision/model.rknn', b'example'))
        self.assertEqual(checker.inspect_file('.env.example', b'HOST=localhost'), [])

    def test_large_file_rejected_but_small_binary_docs_allowed(self):
        self.assertTrue(checker.inspect_file('large.pdf', b'0' * (checker.LIMIT + 1)))
        self.assertEqual(checker.inspect_file('说明.docx', b'PK\x03\x04'), [])

if __name__ == '__main__':
    unittest.main()
