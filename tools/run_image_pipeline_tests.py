"""Compile RTL and compare every output with an independent image reference.

Requires Icarus Verilog (iverilog and vvp); no Python third-party packages.
Run from any directory: python tools/run_image_pipeline_tests.py
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Config:
    w: int = 4
    h: int = 3
    rx: int = 0
    ry: int = 0
    rw: int = 4
    rh: int = 3
    flags: int = 0
    gain: int = 64
    bias: int = 0
    tag: int = 0


class Suite:
    def __init__(self):
        self.commands = []
        self.expected = defaultdict(list)
        self.frame_count = 0
        self.rng = random.Random(2476)
        self.cases = []

    def cmd(self, op, cam=0, *values):
        values = list(values) + [0] * (5 - len(values))
        self.commands.append(f"{op} {cam} " + " ".join(f"{v & 0xffffffff:08x}" for v in values))

    def write(self, cam, addr, value):
        self.cmd(1, cam, addr, value)

    def config(self, cam, cfg, commit=True):
        for address, data in (
            (0, cfg.w | cfg.h << 16), (4, cfg.rx | cfg.ry << 16),
            (8, cfg.rw | cfg.rh << 16), (12, cfg.flags),
            (16, cfg.gain | (cfg.bias & 511) << 16), (20, cfg.tag),
        ):
            self.write(cam, address, data)
        if commit:
            self.write(cam, 24, 1)

    def pixels(self, cfg, pattern):
        if pattern == "random":
            return [[self.rng.randrange(256) for _ in range(cfg.w)] for _ in range(cfg.h)]
        return [[(
            157 if pattern == "constant" else
            255 * ((x + y) % 2) if pattern == "checker" else
            255 * (x == cfg.w // 2 and y == cfg.h // 2) if pattern == "impulse" else
            (x * 37 + y * 91) % 256
        ) for x in range(cfg.w)] for y in range(cfg.h)]

    def expect(self, cam, cfg, pixels, fid, timestamp):
        # Direct 9-tap convolution: intentionally independent of RTL row banks,
        # RAM cycles, shift registers, and synthetic border tokens.
        weights = ((1, 2, 1), (2, 4, 2), (1, 2, 1))
        for y in range(cfg.h):
            for x in range(cfg.w):
                raw = pixels[y][x]
                total = sum(
                    weights[dy + 1][dx + 1]
                    * pixels[min(cfg.h - 1, max(0, y + dy))][min(cfg.w - 1, max(0, x + dx))]
                    for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                )
                source = (total + 8) // 16 if cfg.flags & 1 else raw
                adjusted = min(255, max(0, (source * cfg.gain + 32) // 64 + cfg.bias))
                metadata = (((((cfg.tag << 64) | timestamp) << 32 | fid) << 16 | y) << 16 | x) << 3
                flags = int(x == 0 and y == 0) | int(x == cfg.w - 1) << 1 | int(x == cfg.w - 1 and y == cfg.h - 1) << 2
                self.expected['F', cam].append((raw | adjusted << 8, metadata | flags))
                ex, ey = min(cfg.w, cfg.rx + cfg.rw), min(cfg.h, cfg.ry + cfg.rh)
                if cfg.flags & 2 and cfg.rx <= x < ex and cfg.ry <= y < ey:
                    rflags = int(x == cfg.rx and y == cfg.ry) | int(x == ex - 1) << 1 | int(x == ex - 1 and y == ey - 1) << 2
                    self.expected['R', cam].append((adjusted if cfg.flags & 4 else raw, metadata | rflags))

    def pixel(self, cam, cfg, pixels, i, fid, timestamp):
        y, x = divmod(i, cfg.w)
        flags = int(i == 0) | int(x == cfg.w - 1) << 1
        # Subsequent-beat metadata is deliberately different: only SOF values
        # may determine the output frame id and timestamp.
        self.cmd(2, cam, pixels[y][x], flags, fid if i == 0 else 0xdeadbeef,
                 timestamp >> 32 if i == 0 else 0xbad, timestamp & 0xffffffff if i == 0 else 0xf00d)

    def frame(self, cam, cfg, pattern="random", configure=True, mid=None):
        if configure:
            self.config(cam, cfg)
        self.frame_count += 1
        fid = self.frame_count + cam * 0x10000
        timestamp = 0x1234567800000000 + self.frame_count * 100003
        pixels = self.pixels(cfg, pattern)
        self.expect(cam, cfg, pixels, fid, timestamp)
        for i in range(cfg.w * cfg.h):
            self.pixel(cam, cfg, pixels, i, fid, timestamp)
            if mid and i == cfg.w * cfg.h // 2:
                mid()

    def build(self):
        self.cases.append("replicated borders, sizes 1x1/1xN/Nx1/odd/max-width/max-height, five image patterns")
        for j, (w, h) in enumerate(((1, 1), (1, 9), (9, 1), (2, 2), (3, 7), (17, 13), (2048, 3), (3, 2048))):
            for p, pattern in enumerate(("constant", "ramp", "impulse", "checker", "random")):
                cfg = Config(w, h, 0, 0, w, h, 7, 64, 0, j * 5 + p + 1)
                self.frame((j + p) % 2, cfg, pattern)
        self.cases.append("ROI raw/processed, disabled/zero/outside/clipped/16-bit overflow, signed luma saturation")
        variants = (
            (0, 0, 7, 5, 0, 64, 0), (2, 1, 3, 2, 2, 64, 0),
            (2, 1, 3, 2, 7, 96, -19), (6, 4, 65535, 65535, 7, 255, 255),
            (7, 0, 9, 5, 7, 0, -256), (0, 5, 7, 9, 7, 64, 0),
            (65535, 65535, 65535, 65535, 7, 64, 0), (0, 0, 0, 5, 7, 64, 0),
            (0, 0, 7, 0, 7, 64, 0), (0, 0, 7, 5, 6, 0, 123),
        )
        for j, values in enumerate(variants):
            self.frame(j % 2, Config(7, 5, *values, tag=100+j))
        self.cases.append("atomic next-SOF commit and immutable pending snapshot while shadow registers change")
        current = Config(8, 6, 1, 1, 4, 3, 7, 64, 0, 201)
        future = Config(5, 4, 2, 1, 8, 2, 6, 71, -5, 202)
        shadow_only = Config(2, 9, 0, 0, 1, 2, 7, 11, 199, 203)
        def update():
            self.config(0, future)
            self.cmd(6, 0, 1, 1)
            self.config(0, shadow_only, commit=False)
        self.frame(0, current, mid=update)
        self.frame(0, future, configure=False)
        self.cmd(6, 0, 1, 0)
        self.write(0, 24, 1)
        self.frame(0, shadow_only, configure=False)
        self.cases.append("simultaneous live lanes, independent frame sizes/metadata and ROI backpressure")
        c0, c1 = Config(13, 9, 3, 2, 7, 4, 7, tag=301), Config(9, 13, 1, 3, 5, 5, 3, tag=302)
        self.config(0, c0); self.config(1, c1)
        p0, p1 = self.pixels(c0, "random"), self.pixels(c1, "random")
        self.expect(0, c0, p0, 0xfffffffe, 0xffffffffffffffff)
        self.expect(1, c1, p1, 0xffffffff, 0x8000000000000001)
        self.frame_count += 2
        for i in range(117):
            self.pixel(0, c0, p0, i, 0xfffffffe, 0xffffffffffffffff)
            self.pixel(1, c1, p1, i, 0xffffffff, 0x8000000000000001)
        self.cmd(5, 0, 100)
        self.cases.append("lane 0 output blocked while lane 1 finishes; reset drops a stalled partial frame")
        self.cmd(4, 0, 2, 2, 0)
        self.config(0, Config())
        for i in range(6):
            self.cmd(2, 0, i, int(i == 0) | int(i % 4 == 3) << 1, 777, 0, 888)
        self.cmd(5, 0, 20)
        self.frame(1, Config(4, 3, 0, 0, 4, 3, 7, tag=333))
        self.cmd(5, 0, 100)
        self.cmd(6, 1, 4, len(self.expected['F', 1]))
        self.cmd(3)
        self.cmd(4, 0, 3, 3, 1)
        self.frame(0, Config(3, 2, 0, 0, 3, 2, 7, tag=334))
        self.cmd(5, 0, 100)
        self.cases.append("invalid dimensions/unknown address and malformed SOF/EOL stop until reset")
        error_count = 0
        for w, h in ((0, 3), (4, 0), (2049, 3), (4, 2049)):
            self.write(0, 0, w | h << 16); self.write(0, 24, 1)
            error_count += 1
            self.cmd(5, 0, 3); self.cmd(6, 0, 2, error_count); self.cmd(6, 0, 1, 0)
        self.write(0, 0x3c, 123); error_count += 1
        self.cmd(5, 0, 3); self.cmd(6, 0, 2, error_count)
        for malformed in ((0,), (3,), (1, 1), (1, 0, 0, 0)):
            self.cmd(3)
            for flags in malformed:
                self.cmd(2, 0, 55, flags, 1, 0, 99)
            self.cmd(5, 0, 5); self.cmd(6, 0, 0, 1); self.cmd(6, 0, 3)
        self.cmd(3)
        self.cmd(6, 0, 0, 0)
        self.frame(0, Config(), "ramp", configure=False)
        self.frame(1, Config(), "random", configure=False)
        self.cmd(5, 0, 100)
        self.cmd(6, 0, 0, 0)
        return self


def run(command, directory, log_name):
    result = subprocess.run([str(x) for x in command], cwd=directory, capture_output=True, text=True, timeout=180)
    (directory / log_name).write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}); see {directory / log_name}\n{result.stdout[-2000:]}{result.stderr[-2000:]}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iverilog-dir", type=Path, default=ROOT / ".tools/iverilog/app/bin")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--waves", action="store_true")
    args = parser.parse_args()
    run_dir = (args.out or ROOT / "tmp" / ("afh03-image-tests-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))).resolve()
    run_dir.mkdir(parents=True, exist_ok=False)
    def exe(name):
        local = args.iverilog_dir / (name + ".exe")
        found = local if local.is_file() else shutil.which(name)
        if not found:
            raise FileNotFoundError(f"Install Icarus Verilog or pass --iverilog-dir: missing {name}")
        return found
    iv, vvp = exe("iverilog"), exe("vvp")
    rtl = sorted((ROOT / "fpga/rtl/afh03_image").glob("*.v"))
    source_files = rtl + sorted((ROOT / "fpga/sim/afh03_image").glob("*.sv")) + [Path(__file__).resolve()]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    for bench in ("tb_image", "tb_rgb_luma"):
        run([iv, "-g2012", "-Wall", "-s", bench, "-o", bench + ".vvp", *rtl,
             ROOT / "fpga/sim/afh03_image" / (bench + ".sv")], run_dir, bench + "-compile.log")
    suite = Suite().build()
    (run_dir / "stimulus.txt").write_text("\n".join(suite.commands) + "\n", encoding="ascii")
    seeds = (1, 2476, 314159)
    for seed in seeds:
        result = run([vvp, "tb_image.vvp", "+STIM=stimulus.txt", f"+OUT=output-{seed}.txt", f"+SEED={seed}"]
                     + (["+WAVES"] if args.waves and seed == seeds[0] else []), run_dir, f"simulation-{seed}.log")
        if "TB_IMAGE_PASS" not in result:
            raise AssertionError("Simulation has no success marker")
        actual = defaultdict(list)
        for line in (run_dir / f"output-{seed}.txt").read_text().splitlines():
            kind, camera, data, metadata = line.split()
            actual[kind, int(camera)].append((int(data, 16), int(metadata, 16)))
        for key in suite.expected.keys() | actual.keys():
            expected, observed = suite.expected[key], actual[key]
            if len(expected) != len(observed):
                raise AssertionError(f"Seed {seed} {key}: count {len(observed)} != {len(expected)}; outputs {run_dir}")
            for index, (want, got) in enumerate(zip(expected, observed)):
                if want != got:
                    raise AssertionError(f"Seed {seed} {key} pixel {index}: got {got}, expected {want}; outputs {run_dir}")
        print(f"PASS seed={seed}: {sum(map(len, actual.values()))} output beats matched")
    rgb = run([vvp, "tb_rgb_luma.vvp"], run_dir, "rgb-luma.log")
    if "TB_RGB_LUMA_PASS" not in rgb:
        raise AssertionError("RGB/luma tests have no success marker")
    summary = {
        "status": "PASS", "frame_count_per_seed": suite.frame_count,
        "full_pixels_per_seed": sum(len(v) for (k, _), v in suite.expected.items() if k == 'F'),
        "roi_pixels_per_seed": sum(len(v) for (k, _), v in suite.expected.items() if k == 'R'),
        "random_stall_seeds": seeds, "rgb_pixels": 4096, "luma_cases": 327680,
        "coverage": suite.cases, "source_sha256": hashes,
        "iverilog_version": run([iv, "-V"], run_dir, "iverilog-version.log").splitlines()[0],
        "hardware_tested": False,
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(rgb.strip())
    print(f"PASS: {suite.frame_count} frames per seed. Reports: {run_dir}")


if __name__ == "__main__":
    main()
