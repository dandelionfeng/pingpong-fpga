/*
 * Coordinate tests for the PURE MANUAL annotation tool.
 *
 * Run with:  node tests/test_manual_coords.mjs
 * Exit code 0 = all pass. No browser and no framework required.
 *
 * These tests exist because an earlier tool shipped a crop/zoom -> original
 * mapping bug that shifted every box. The transform is therefore proven here,
 * not eyeballed.
 */

import assert from 'node:assert/strict';
import {
  clamp,
  makeView,
  displayToImage,
  imageToDisplay,
  normalizeBox,
  isValidBox,
  boxToYolo,
  yoloToBox,
  boxDelta,
  resizeBox,
  handlePoint,
  HANDLES,
} from '../vision/bndstt_mvp/manual_web/coords.mjs';

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`  ok   ${name}`);
  } catch (error) {
    failed += 1;
    console.log(`  FAIL ${name}\n       ${error.message}`);
  }
}

const NATURAL = { width: 1920, height: 1080 };

console.log('manual annotation coordinate tests');

/* ---------------------------------------------------------------- identity */

test('fit-to-viewport of 960x540 gives scale 0.5 and centre maps correctly', () => {
  const view = makeView(NATURAL, { width: 960, height: 540 }, 1, { x: 0, y: 0 });
  assert.equal(view.scale, 0.5);
  const centre = displayToImage(view, 480, 270);
  assert.equal(centre.x, 960);
  assert.equal(centre.y, 540);
});

test('the four viewport corners map to the four image corners', () => {
  const view = makeView(NATURAL, { width: 960, height: 540 }, 1, { x: 0, y: 0 });
  const tl = displayToImage(view, 0, 0);
  const br = displayToImage(view, 960, 540);
  assert.deepEqual([tl.x, tl.y], [0, 0]);
  assert.deepEqual([br.x, br.y], [1920, 1080]);
});

/* -------------------------------------------------------------------- zoom */

for (const zoom of [1, 2, 4, 8]) {
  test(`zoom ${zoom}x: display->image->display round trip is sub-pixel`, () => {
    const view = makeView(NATURAL, { width: 1200, height: 800 }, zoom, { x: 300, y: 150 });
    let worst = 0;
    for (let dx = 0; dx <= 1200; dx += 37) {
      for (let dy = 0; dy <= 800; dy += 29) {
        const img = displayToImage(view, dx, dy);
        const back = imageToDisplay(view, img.x, img.y);
        worst = Math.max(worst, Math.abs(back.x - dx), Math.abs(back.y - dy));
      }
    }
    assert.ok(worst < 1e-9, `round trip error ${worst} must be ~0`);
  });
}

test('zoom 2x doubles the on-screen distance between two image points', () => {
  const v1 = makeView(NATURAL, { width: 1200, height: 800 }, 1, { x: 0, y: 0 });
  const v2 = makeView(NATURAL, { width: 1200, height: 800 }, 2, { x: 0, y: 0 });
  const a1 = imageToDisplay(v1, 100, 100);
  const b1 = imageToDisplay(v1, 200, 100);
  const a2 = imageToDisplay(v2, 100, 100);
  const b2 = imageToDisplay(v2, 200, 100);
  assert.ok(Math.abs((b2.x - a2.x) / (b1.x - a1.x) - 2) < 1e-9);
});

/* --------------------------------------------------------------------- pan */

test('pan shifts the mapping by exactly the panned image offset', () => {
  const base = makeView(NATURAL, { width: 1200, height: 800 }, 2, { x: 0, y: 0 });
  const panned = makeView(NATURAL, { width: 1200, height: 800 }, 2, { x: 200, y: 100 });
  // This viewport is zoomed enough that both pan axes are actually available.
  assert.ok(base.maxPanX > 200, 'test setup must allow a 200 px pan on x');
  assert.ok(base.maxPanY > 100, 'test setup must allow a 100 px pan on y');
  const a = displayToImage(base, 500, 300);
  const b = displayToImage(panned, 500, 300);
  // Pushing the pan right moves the same screen point further into the image.
  assert.ok(Math.abs((b.x - a.x) - 200) < 1e-9, `x delta was ${b.x - a.x}`);
  assert.ok(Math.abs((b.y - a.y) - 100) < 1e-9, `y delta was ${b.y - a.y}`);
});

test('pan clamps to zero on an axis where the image already fits', () => {
  // fit = 0.625 -> the full 1920 px width is visible, so no horizontal pan exists.
  const view = makeView(NATURAL, { width: 1200, height: 800 }, 1, { x: 500, y: 0 });
  assert.equal(view.maxPanX, 0);
  assert.equal(view.pan.x, 0);
});

test('pan is clamped so the image can never leave the viewport', () => {
  const view = makeView(NATURAL, { width: 1200, height: 800 }, 1, { x: 99999, y: 99999 });
  assert.ok(view.pan.x <= view.maxPanX + 1e-9);
  assert.ok(view.pan.y <= view.maxPanY + 1e-9);
  const topLeft = displayToImage(view, 0, 0);
  assert.ok(topLeft.x >= 0 && topLeft.y >= 0);
  assert.ok(topLeft.x + view.viewport.width / view.scale <= NATURAL.width + 1e-6);
});

test('a zoomed view keeps the panned point at the viewport origin', () => {
  const view = makeView(NATURAL, { width: 1200, height: 800 }, 4, { x: 800, y: 400 });
  const origin = displayToImage(view, 0, 0);
  assert.ok(Math.abs(origin.x - view.pan.x) < 1e-9);
  assert.ok(Math.abs(origin.y - view.pan.y) < 1e-9);
});

/* ------------------------------------------------------------------- boxes */

test('drag in either direction yields the same normalised box', () => {
  const view = makeView(NATURAL, { width: 960, height: 540 }, 1, { x: 0, y: 0 });
  const forward = normalizeBox(view, 100, 200, 300, 400);
  const backward = normalizeBox(view, 300, 400, 100, 200);
  assert.deepEqual(forward, backward);
  assert.deepEqual(forward, [100, 200, 300, 400]);
});

test('display drag maps to the correct image box at 0.5 scale', () => {
  const view = makeView(NATURAL, { width: 960, height: 540 }, 1, { x: 0, y: 0 });
  const a = displayToImage(view, 100, 100);
  const b = displayToImage(view, 200, 200);
  const box = normalizeBox(view, a.x, a.y, b.x, b.y);
  assert.deepEqual(box, [200, 200, 400, 400]);
});

test('display drag maps to the correct image box when zoomed 4x and panned', () => {
  const view = makeView(NATURAL, { width: 1200, height: 800 }, 4, { x: 400, y: 200 });
  const a = displayToImage(view, 0, 0);
  const b = displayToImage(view, view.scale * 50, view.scale * 25);
  const box = normalizeBox(view, a.x, a.y, b.x, b.y);
  assert.ok(boxDelta(box, [400, 200, 450, 225]) < 0.01);
});

test('boxes outside the image are clamped, never negative', () => {
  const view = makeView(NATURAL, { width: 960, height: 540 }, 1, { x: 0, y: 0 });
  const box = normalizeBox(view, -500, -500, 5000, 5000);
  assert.deepEqual(box, [0, 0, 1920, 1080]);
});

test('a degenerate drag is rejected as invalid', () => {
  const view = makeView(NATURAL, { width: 960, height: 540 }, 1, { x: 0, y: 0 });
  const tiny = normalizeBox(view, 10, 10, 10.5, 10.5);
  assert.equal(isValidBox(tiny, NATURAL), false);
  assert.equal(isValidBox([0, 0, 10, 10], NATURAL), true);
  assert.equal(isValidBox([0, 0, 10, 5000], NATURAL), false);
  assert.equal(isValidBox([10, 10, 5, 20], NATURAL), false);
  assert.equal(isValidBox([0, 0, Number.NaN, 10], NATURAL), false);
});

/* -------------------------------------------------------------- resize ops */

for (const handle of HANDLES) {
  test(`resize via ${handle} keeps the box valid and inside the image`, () => {
    const view = makeView(NATURAL, { width: 1200, height: 800 }, 2, { x: 0, y: 0 });
    const start = [400, 300, 700, 600];
    const target = displayToImage(view, 50, 50);
    const box = resizeBox(start, handle, target.x, target.y, view);
    assert.ok(isValidBox(box, NATURAL), `box ${box} must stay valid`);
  });
}

test('resizing the east edge only moves the east edge', () => {
  const view = makeView(NATURAL, { width: 1200, height: 800 }, 1, { x: 0, y: 0 });
  const box = resizeBox([100, 100, 200, 200], 'e', 350, 999, view);
  assert.equal(box[0], 100);
  assert.equal(box[1], 100);
  assert.equal(box[3], 200);
  assert.ok(Math.abs(box[2] - 350) < 1e-6);
});

test('handlePoint returns display coordinates consistent with imageToDisplay', () => {
  const view = makeView(NATURAL, { width: 1200, height: 800 }, 3, { x: 200, y: 100 });
  const box = [300, 200, 500, 400];
  const expected = imageToDisplay(view, 300, 200);
  const got = handlePoint(view, box, 'nw');
  assert.ok(Math.abs(got.x - expected.x) < 1e-9);
  assert.ok(Math.abs(got.y - expected.y) < 1e-9);
});

/* -------------------------------------------------------- yolo round trips */

test('pixel XYXY -> YOLO -> pixel XYXY round trip is within 1 pixel', () => {
  const boxes = [
    [0, 0, 10, 10],
    [510, 215, 542, 249],
    [1900, 1060, 1920, 1080],
    [960, 540, 961, 541],
    [123, 45, 1876, 1032],
  ];
  let worst = 0;
  for (const box of boxes) {
    const yolo = boxToYolo(box, NATURAL);
    for (const v of yolo) assert.ok(v >= 0 && v <= 1, `normalised ${v} out of range`);
    const back = yoloToBox(yolo, NATURAL);
    worst = Math.max(worst, boxDelta(box, back));
  }
  assert.ok(worst <= 1, `worst round trip error ${worst} must be <= 1 pixel`);
});

test('a known box converts to the exact expected YOLO values', () => {
  const yolo = boxToYolo([960, 540, 1152, 648], NATURAL);
  assert.ok(Math.abs(yolo[0] - 0.55) < 1e-9);
  assert.ok(Math.abs(yolo[1] - 0.55) < 1e-9);
  assert.ok(Math.abs(yolo[2] - 0.1) < 1e-9);
  assert.ok(Math.abs(yolo[3] - 0.1) < 1e-9);
});

test('non-square images use width and height independently', () => {
  const wide = { width: 2000, height: 500 };
  const yolo = boxToYolo([0, 0, 2000, 500], wide);
  assert.ok(Math.abs(yolo[0] - 0.5) < 1e-12);
  assert.ok(Math.abs(yolo[1] - 0.5) < 1e-12);
  assert.ok(Math.abs(yolo[2] - 1) < 1e-12);
  assert.ok(Math.abs(yolo[3] - 1) < 1e-12);
});

/* ------------------------------------------------------------------- misc */

test('clamp behaves on both ends', () => {
  assert.equal(clamp(-5, 0, 10), 0);
  assert.equal(clamp(15, 0, 10), 10);
  assert.equal(clamp(5, 0, 10), 5);
});

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
