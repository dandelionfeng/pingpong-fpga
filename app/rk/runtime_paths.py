"""Single OpenCV library-directory policy for the RK deployment scripts.

Resolution order:
1. CHAIN_OPENCV_LIB_DIR, absolute or relative to the repository root.
2. Common project-relative locations: opencv/lib, third_party/opencv/lib,
   runtime/opencv/lib and app/rk/opencv/lib.
3. Standard Linux OpenCV library directories.

The resolver validates that a directory actually contains an OpenCV core
library. It never falls back to the old developer-machine path.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]

_CORE_PATTERNS = (
    "libopencv_core.so*",
    "libopencv_core.*",
    "opencv_core*.dll",
    "opencv_world*.dll",
    "opencv_world*.lib",
)
_SYSTEM_DIRS = (
    Path("/usr/local/lib"),
    Path("/usr/lib/aarch64-linux-gnu"),
    Path("/usr/lib64"),
    Path("/usr/lib"),
    Path("/opt/opencv/lib"),
)


class OpenCVPathError(RuntimeError):
    """No usable OpenCV library directory was found."""


def _has_opencv_core(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    return any(any(directory.glob(pattern)) for pattern in _CORE_PATTERNS)


def _resolve_relative(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def _project_candidates(root: Path) -> Iterable[Path]:
    yield root / "opencv" / "lib"
    yield root / "third_party" / "opencv" / "lib"
    yield root / "runtime" / "opencv" / "lib"
    yield root / "app" / "rk" / "opencv" / "lib"


def resolve_opencv_lib_dir(root: Optional[Path] = None,
                           environ: Optional[Dict[str, str]] = None) -> Path:
    """Return the validated OpenCV library directory or raise OpenCVPathError."""
    root = (root or ROOT).resolve()
    env = os.environ if environ is None else environ
    explicit = env.get("CHAIN_OPENCV_LIB_DIR", "").strip()

    if explicit:
        candidate = _resolve_relative(explicit, root)
        if not _has_opencv_core(candidate):
            raise OpenCVPathError(
                "CHAIN_OPENCV_LIB_DIR is set but does not contain an OpenCV core library: "
                f"{candidate}. Expected libopencv_core.so* or opencv_world*.dll."
            )
        return candidate

    searched = []
    for candidate in list(_project_candidates(root)) + list(_SYSTEM_DIRS):
        searched.append(str(candidate))
        if _has_opencv_core(candidate):
            return candidate.resolve()

    raise OpenCVPathError(
        "OpenCV library directory is not configured. Set CHAIN_OPENCV_LIB_DIR "
        "to a directory containing libopencv_core.so* (or opencv_world*.dll), "
        "or place the libraries in one of: "
        + ", ".join(searched)
    )


def with_opencv_library_path(existing: str, lib_dir: Path) -> str:
    """Prepend lib_dir to an existing LD_LIBRARY_PATH without dropping entries."""
    parts = [str(lib_dir)]
    if existing:
        parts.extend(part for part in existing.split(os.pathsep) if part and part != str(lib_dir))
    return os.pathsep.join(parts)


def environment_with_opencv(root: Optional[Path] = None,
                            environ: Optional[Dict[str, str]] = None) -> Tuple[Path, Dict[str, str]]:
    """Return (lib_dir, env) with CHAIN_OPENCV_LIB_DIR and LD_LIBRARY_PATH set."""
    env = dict(os.environ if environ is None else environ)
    lib_dir = resolve_opencv_lib_dir(root, env)
    env["CHAIN_OPENCV_LIB_DIR"] = str(lib_dir)
    env["LD_LIBRARY_PATH"] = with_opencv_library_path(env.get("LD_LIBRARY_PATH", ""), lib_dir)
    return lib_dir, env
