/*
 * Pure coordinate transforms for the PURE MANUAL annotation tool.
 *
 * ONE canonical space exists: ORIGINAL IMAGE PIXELS (XYXY on current_origin).
 * Everything the browser draws is in DISPLAY space and is converted through
 * these functions. They are pure and deterministic so they can be unit tested
 * without a browser (tests/test_manual_coords.mjs).
 *
 * Display space is defined as:
 *   display_x = (image_x - pan_x) * scale
 *   display_y = (image_y - pan_y) * scale
 * where scale already folds together the fit-to-viewport factor and the user zoom.
 * pan_x / pan_y are in IMAGE pixels (the image point shown at the top-left of the
 * viewport), which keeps the maths independent of the viewport size.
 */

export const MIN_BOX = 2; // an image-space box narrower/shorter than this is rejected

/** Clamp a number into [lo, hi]. */
export function clamp(value, lo, hi) {
  return value < lo ? lo : value > hi ? hi : value;
}

/**
 * Build the immutable view transform for one render.
 * @param {{width:number,height:number}} natural  natural image size in pixels
 * @param {{width:number,height:number}} viewport CSS pixel size of the canvas area
 * @param {number} zoom  user zoom multiplier (1, 2, 4, 8 ...)
 * @param {{x:number,y:number}} pan  top-left image point shown, in image pixels
 */
export function makeView(natural, viewport, zoom = 1, pan = { x: 0, y: 0 }) {
  const fit = Math.min(viewport.width / natural.width, viewport.height / natural.height);
  const scale = fit * zoom;
  // Keep the panned region inside the image so the user can never pan into blank space.
  const visibleW = viewport.width / scale;
  const visibleH = viewport.height / scale;
  const maxPanX = Math.max(0, natural.width - visibleW);
  const maxPanY = Math.max(0, natural.height - visibleH);
  return {
    natural,
    viewport,
    zoom,
    fit,
    scale,
    pan: { x: clamp(pan.x, 0, maxPanX), y: clamp(pan.y, 0, maxPanY) },
    maxPanX,
    maxPanY,
  };
}

/** Display (CSS px inside the canvas area) -> original image pixels. */
export function displayToImage(view, dx, dy) {
  return { x: view.pan.x + dx / view.scale, y: view.pan.y + dy / view.scale };
}

/** Original image pixels -> display (CSS px inside the canvas area). */
export function imageToDisplay(view, ix, iy) {
  return { x: (ix - view.pan.x) * view.scale, y: (iy - view.pan.y) * view.scale };
}

/** Order two image-space corners into a valid XYXY box, clamped to the image. */
export function normalizeBox(view, ax, ay, bx, by) {
  const x1 = clamp(Math.min(ax, bx), 0, view.natural.width);
  const y1 = clamp(Math.min(ay, by), 0, view.natural.height);
  const x2 = clamp(Math.max(ax, bx), 0, view.natural.width);
  const y2 = clamp(Math.max(ay, by), 0, view.natural.height);
  return [round2(x1), round2(y1), round2(x2), round2(y2)];
}

/** A box is usable only when both sides have real extent. */
export function isValidBox(box, natural) {
  if (!Array.isArray(box) || box.length !== 4) return false;
  const [x1, y1, x2, y2] = box;
  if (![x1, y1, x2, y2].every((v) => Number.isFinite(v))) return false;
  if (!(x1 < x2 && y1 < y2)) return false;
  if (x2 - x1 < MIN_BOX || y2 - y1 < MIN_BOX) return false;
  return x1 >= 0 && y1 >= 0 && x2 <= natural.width && y2 <= natural.height;
}

export function round2(value) {
  return Math.round(value * 100) / 100;
}

/** Bounding box of a set of boxes; used for fit-to-objects. */
export function boxesExtent(boxes) {
  if (!boxes.length) return null;
  let x1 = Infinity;
  let y1 = Infinity;
  let x2 = -Infinity;
  let y2 = -Infinity;
  for (const b of boxes) {
    x1 = Math.min(x1, b[0]);
    y1 = Math.min(y1, b[1]);
    x2 = Math.max(x2, b[2]);
    y2 = Math.max(y2, b[3]);
  }
  return [x1, y1, x2, y2];
}

/** Original pixel XYXY -> normalised YOLO [xc, yc, w, h] in [0,1]. */
export function boxToYolo(box, natural) {
  const [x1, y1, x2, y2] = box;
  const xc = (x1 + x2) / 2 / natural.width;
  const yc = (y1 + y2) / 2 / natural.height;
  const w = (x2 - x1) / natural.width;
  const h = (y2 - y1) / natural.height;
  return [xc, yc, w, h];
}

/** Normalised YOLO -> original pixel XYXY. */
export function yoloToBox(yolo, natural) {
  const [xc, yc, w, h] = yolo;
  const x1 = (xc - w / 2) * natural.width;
  const y1 = (yc - h / 2) * natural.height;
  const x2 = (xc + w / 2) * natural.width;
  const y2 = (yc + h / 2) * natural.height;
  return [round2(x1), round2(y1), round2(x2), round2(y2)];
}

/** Largest absolute per-coordinate difference between two XYXY boxes. */
export function boxDelta(a, b) {
  return Math.max(...a.map((v, i) => Math.abs(v - b[i])));
}

/** The eight resize handles of a box, in display space, for hit testing. */
export const HANDLES = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];

export function handlePoint(view, box, handle) {
  const [x1, y1, x2, y2] = box;
  const midX = (x1 + x2) / 2;
  const midY = (y1 + y2) / 2;
  const table = {
    nw: [x1, y1], n: [midX, y1], ne: [x2, y1], e: [x2, midY],
    se: [x2, y2], s: [midX, y2], sw: [x1, y2], w: [x1, midY],
  };
  const [ix, iy] = table[handle];
  return imageToDisplay(view, ix, iy);
}

/** Apply a handle drag, keeping the opposite edge/corner anchored. */
export function resizeBox(box, handle, ix, iy, view) {
  let [x1, y1, x2, y2] = box;
  if (handle.includes('w')) x1 = ix;
  if (handle.includes('e')) x2 = ix;
  if (handle.includes('n')) y1 = iy;
  if (handle.includes('s')) y2 = iy;
  return normalizeBox(view, x1, y1, x2, y2);
}

export const CLASSES = [
  { id: 0, name: 'ball', color: '#ff3b30' },
  { id: 1, name: 'hand', color: '#28c76f' },
  { id: 2, name: 'racket', color: '#ff9f0a' },
];

export function classById(id) {
  return CLASSES.find((c) => c.id === id) || null;
}
