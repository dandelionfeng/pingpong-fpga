import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app" / "rk"))

from runtime_paths import (  # noqa: E402
    OpenCVPathError,
    environment_with_opencv,
    resolve_opencv_lib_dir,
    with_opencv_library_path,
)


def make_opencv(root: Path, relative: str = "opencv/lib") -> Path:
    path = root / relative
    path.mkdir(parents=True, exist_ok=True)
    (path / "libopencv_core.so.4.10").write_bytes(b"")
    return path


class RuntimePathsTest(unittest.TestCase):
    def test_explicit_absolute_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib = make_opencv(root, "custom/opencv")
            self.assertEqual(resolve_opencv_lib_dir(root, {"CHAIN_OPENCV_LIB_DIR": str(lib)}), lib)

    def test_explicit_relative_directory_is_relative_to_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib = make_opencv(root, "third_party/opencv/lib")
            self.assertEqual(
                resolve_opencv_lib_dir(root, {"CHAIN_OPENCV_LIB_DIR": "third_party/opencv/lib"}),
                lib.resolve(),
            )

    def test_project_relative_fallback_without_env(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib = make_opencv(root, "runtime/opencv/lib")
            self.assertEqual(resolve_opencv_lib_dir(root, {}), lib.resolve())

    def test_changed_root_and_cwd(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib = make_opencv(root, "opencv/lib")
            old = os.getcwd()
            try:
                os.chdir(tempfile.gettempdir())
                self.assertEqual(resolve_opencv_lib_dir(root, {}), lib.resolve())
            finally:
                os.chdir(old)

    def test_missing_configuration_raises(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(OpenCVPathError) as ctx:
                resolve_opencv_lib_dir(Path(td), {})
            self.assertIn("CHAIN_OPENCV_LIB_DIR", str(ctx.exception))

    def test_invalid_explicit_directory_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            make_opencv(root, "opencv/lib")
            with self.assertRaises(OpenCVPathError) as ctx:
                resolve_opencv_lib_dir(root, {"CHAIN_OPENCV_LIB_DIR": str(root / "missing")})
            self.assertIn("does not contain", str(ctx.exception))

    def test_ld_library_path_is_prepended_and_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            lib = Path(td) / "lib"
            lib.mkdir()
            existing = os.pathsep.join(["/opt/one", "/opt/two"])
            self.assertEqual(
                with_opencv_library_path(existing, lib),
                os.pathsep.join([str(lib), "/opt/one", "/opt/two"]),
            )

    def test_environment_sets_validated_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lib = make_opencv(root, "opencv/lib")
            lib_dir, env = environment_with_opencv(root, {"LD_LIBRARY_PATH": "/opt/existing"})
            self.assertEqual(lib_dir, lib.resolve())
            self.assertEqual(env["CHAIN_OPENCV_LIB_DIR"], str(lib.resolve()))
            self.assertTrue(env["LD_LIBRARY_PATH"].startswith(str(lib.resolve()) + os.pathsep))


if __name__ == "__main__":
    unittest.main()
