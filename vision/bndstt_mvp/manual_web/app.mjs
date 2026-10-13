/*
 * PURE MANUAL annotation app for BNDSTT_MANUAL_GT_V1.
 *
 * The only canonical coordinates are ORIGINAL current_origin pixels. Everything
 * drawn on screen is converted through coords.mjs, which is unit tested in
 * tests/test_manual_coords.mjs. No box is ever proposed or pre-filled by this
 * page: the canvas starts empty and only shows what a human saved.
 */

import {
  CLASSES,
  classById,
  makeView,
  displayToImage,
  imageToDisplay,
  normalizeBox,
  isValidBox,
  resizeBox,
  handlePoint,
  HANDLES,
  boxesExtent,
  boxDelta,
  clamp,
} from './coords.mjs';

const ZOOMS = [1, 2, 4, 8, 16];
const HANDLE_HIT = 7;
const STATE_COLORS = {
  UNLABELED: '#9aa3b5',
  MANUAL_IN_PROGRESS: '#ffd27f',
  MANUAL_REVIEWED: '#28c76f',
  NEEDS_REVIEW: '#ff3b30',
};

const el = (id) => document.getElementById(id);
const stage = el('stage');
const viewport = el('viewport');
const mainimg = el('mainimg');
const overlay = el('overlay');
const capture = el('capture');
const toast = el('toast');

let state = {
  frames: [],
  order: [],
  cursor: -1,
  activeClass: 0,
  boxes: [],
  selected: -1,
  view: null,
  zoomIndex: 0,
  pan: { x: 0, y: 0 },
  gray: false,
  dirty: false,
  qaMode: false,
  undo: [],
  redo: [],
  natural: { width: 1920, height: 1080 },
  filter: 'ALL',
};

let drag = null;

/* ------------------------------------------------------------------ helpers */

function showToast(message, kind = 'info', ms = 2600) {
  toast.textContent = message;
  toast.className = kind;
  if (ms > 0) setTimeout(() => { toast.className = ''; }, ms);
}

function currentFrame() {
  return state.cursor >= 0 ? state.frames[state.order[state.cursor]] : null;
}

function snapshot() {
  return JSON.stringify(state.boxes);
}

function pushUndo() {
  state.undo.push(snapshot());
  if (state.undo.length > 200) state.undo.shift();
  state.redo.length = 0;
  markDirty();
}

function markDirty() {
  state.dirty = true;
  el('h-dirty').textContent = '● 未保存';
  el('h-dirty').style.color = '#ffd27f';
}

function markClean() {
  state.dirty = false;
  el('h-dirty').textContent = '';
}

function rebuildOrder(keepId) {
  const filter = state.filter;
  const keep = keepId || currentFrame()?.image_id;
  state.order = state.frames
    .map((f, i) => i)
    .filter((i) => {
      const f = state.frames[i];
      switch (filter) {
        case 'UNLABELED': return f.review_state === 'UNLABELED' || f.review_state === 'MANUAL_IN_PROGRESS';
        case 'MANUAL_REVIEWED': return f.review_state === 'MANUAL_REVIEWED';
        case 'NEEDS_REVIEW': return f.review_state === 'NEEDS_REVIEW';
        case 'TRAIN': return f.split === 'train';
        case 'VAL': return f.split === 'val';
        default: return true;
      }
    });
  const at = keep ? state.order.findIndex((i) => state.frames[i].image_id === keep) : -1;
  state.cursor = at >= 0 ? at : (state.order.length ? 0 : -1);
}

/* ------------------------------------------------------------------- render */

function layout() {
  const rect = stage.getBoundingClientRect();
  const zoom = ZOOMS[state.zoomIndex];
  state.view = makeView(
    state.natural,
    { width: rect.width, height: rect.height },
    zoom,
    state.pan,
  );
  state.pan = state.view.pan;
  const scale = state.view.scale;
  const w = state.natural.width * scale;
  const h = state.natural.height * scale;
  viewport.style.width = `${w}px`;
  viewport.style.height = `${h}px`;
  viewport.style.transform = `translate(${-state.pan.x * scale}px, ${-state.pan.y * scale}px)`;
  mainimg.style.width = `${w}px`;
  mainimg.style.height = `${h}px`;
  overlay.setAttribute('width', String(w));
  overlay.setAttribute('height', String(h));
  overlay.setAttribute('viewBox', `0 0 ${w} ${h}`);
  el('h-zoom').textContent = `zoom ${zoom.toFixed(2)}× (显示 ${scale.toFixed(3)})`;
  drawOverlay();
}

function drawOverlay() {
  if (!state.view) return;
  const parts = [];
  state.boxes.forEach((box, index) => {
    const cls = classById(box.class_id);
    const a = imageToDisplay(state.view, box.bbox_xyxy[0], box.bbox_xyxy[1]);
    const b = imageToDisplay(state.view, box.bbox_xyxy[2], box.bbox_xyxy[3]);
    const x = a.x, y = a.y, w = b.x - a.x, h = b.y - a.y;
    const selected = index === state.selected;
    parts.push(
      `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="none" ` +
        `stroke="${cls.color}" stroke-width="${selected ? 3 : 2}" />`,
    );
    parts.push(
      `<text x="${x + 3}" y="${y - 4}" fill="${cls.color}" font-size="13" font-weight="700" ` +
        `style="paint-order:stroke;stroke:#000;stroke-width:3px">${cls.name}</text>`,
    );
    if (selected && !state.qaMode) {
      for (const handle of HANDLES) {
        const point = handlePoint(state.view, box.bbox_xyxy, handle);
        parts.push(
          `<rect x="${point.x - 4}" y="${point.y - 4}" width="8" height="8" ` +
            `fill="#fff" stroke="${cls.color}" stroke-width="2" />`,
        );
      }
    }
  });
  overlay.innerHTML = parts.join('');
}

function renderHeader() {
  const frame = currentFrame();
  if (!frame) return;
  el('h-progress').textContent = `${state.cursor + 1} / ${state.order.length}（总 ${state.frames.length}，index ${frame.image_index + 1}）`;
  el('h-split').textContent = frame.split;
  el('h-session').textContent = frame.session_id;
  el('h-frame').textContent = String(frame.frame_index);
  el('h-stage').textContent = frame.stage_hint || '-';
  el('h-size').textContent = `${frame.width}×${frame.height}`;
  el('h-status').textContent = frame.review_state;
  el('h-status').style.color = STATE_COLORS[frame.review_state] || '#e8eaf0';
  const counts = { 0: 0, 1: 0, 2: 0 };
  for (const box of state.boxes) counts[box.class_id] += 1;
  el('h-counts').textContent = `ball ${counts[0]} · hand ${counts[1]} · racket ${counts[2]}`;
  drawObjectList();
}

function drawObjectList() {
  const host = el('objects');
  if (!state.boxes.length) {
    host.innerHTML = '<span class="hint">当前没有 bbox</span>';
    return;
  }
  host.innerHTML = state.boxes
    .map((box, index) => {
      const cls = classById(box.class_id);
      const [x1, y1, x2, y2] = box.bbox_xyxy;
      const sel = index === state.selected ? ' sel' : '';
      return `<div class="row${sel}" data-index="${index}">
        <span class="sw" style="background:${cls.color}"></span>
        <span>${cls.name}</span>
        <span class="hint">[${x1}, ${y1}, ${x2}, ${y2}]</span></div>`;
    })
    .join('');
  host.querySelectorAll('.row').forEach((row) => {
    row.onclick = () => {
      state.selected = Number(row.dataset.index);
      drawOverlay();
      drawObjectList();
    };
  });
}

function renderStats(stats) {
  if (!stats) return;
  el('s-total').textContent = stats.total;
  el('s-reviewed').textContent = stats.reviewed;
  el('s-needs').textContent = stats.needs_review;
  el('s-remaining').textContent = stats.remaining;
  el('s-ball').textContent = stats.objects.ball;
  el('s-hand').textContent = stats.objects.hand;
  el('s-racket').textContent = stats.objects.racket;
  el('s-split').textContent = `${stats.split.train.reviewed}/${stats.split.val.reviewed} reviewed`;
}

/* --------------------------------------------------------------------- load */

async function loadFrame(force = false) {
  const frame = currentFrame();
  if (!frame) {
    mainimg.removeAttribute('src');
    renderHeader();
    return;
  }
  state.selected = -1;
  state.undo = [];
  state.redo = [];
  state.pan = { x: 0, y: 0 };
  state.zoomIndex = 0;

  const img = new Image();
  img.onload = () => {
    state.natural = { width: img.naturalWidth, height: img.naturalHeight };
    mainimg.src = img.src;
    el('h-size').textContent = `${state.natural.width}×${state.natural.height}`;
    layout();
  };
  img.onerror = () => showToast('主图加载失败：' + frame.image_path, 'err', 6000);
  img.src = mediaUrl(state.gray ? frame.gray3_path : frame.image_path);

  const prev = frame.prev_path || frame.image_path;
  const next = frame.next_path || frame.image_path;
  el('ref-prev').src = mediaUrl(prev);
  el('ref-next').src = mediaUrl(next);
  const crop = el('ref-crop');
  if (frame.crop_reference_path) {
    crop.src = mediaUrl(frame.crop_reference_path);
    crop.parentElement.style.opacity = '1';
  } else {
    crop.removeAttribute('src');
    crop.parentElement.style.opacity = '.35';
  }

  // The ONLY source of boxes is what a human previously saved through this tool.
  const response = await fetch(`/api/annotation?image_id=${encodeURIComponent(frame.image_id)}`);
  const payload = await response.json();
  state.boxes = payload.record ? payload.record.objects.map((o) => ({ ...o, bbox_xyxy: [...o.bbox_xyxy] })) : [];
  renderHeader();
  markClean();
  if (force) drawOverlay();
}

function mediaUrl(relative) {
  const clean = String(relative).replace(/^artifacts\/files\/datasets\/BNDSTT_MVP_v1\//, '');
  return `/media/${clean.split('/').map(encodeURIComponent).join('/')}`;
}

/* ------------------------------------------------------------------ actions */

async function refreshState() {
  const response = await fetch('/api/state');
  const payload = await response.json();
  state.frames = payload.frames.map((f, i) => ({ ...f, image_index: i }));
  renderStats(payload.stats);
  return payload.stats;
}

function selectClass(id) {
  state.activeClass = id;
  document.querySelectorAll('.clsbtn').forEach((b) => {
    b.classList.toggle('on', Number(b.dataset.class) === id);
  });
}

function go(delta) {
  if (state.dirty && !confirm('Unsaved changes.\n\nOK = Discard and move\nCancel = stay here')) return;
  const next = state.cursor + delta;
  if (next < 0 || next >= state.order.length) return;
  state.cursor = next;
  loadFrame();
}

function goToFirstUnlabeled() {
  const at = state.order.findIndex((i) => {
    const s = state.frames[i].review_state;
    return s === 'UNLABELED' || s === 'MANUAL_IN_PROGRESS';
  });
  if (at < 0) { showToast('没有 UNLABELED 图片了', 'info'); return; }
  state.cursor = at;
  loadFrame();
}

function deleteSelected() {
  if (state.selected < 0) return;
  pushUndo();
  state.boxes.splice(state.selected, 1);
  state.selected = -1;
  drawOverlay();
  renderHeader();
}

function clearAll() {
  if (!state.boxes.length) return;
  if (!confirm(`Clear ALL ${state.boxes.length} box(es) on this image?\n\nThis cannot be undone except with Ctrl+Z.`)) return;
  pushUndo();
  state.boxes = [];
  state.selected = -1;
  drawOverlay();
  renderHeader();
}

function undo() {
  if (!state.undo.length) return;
  state.redo.push(snapshot());
  const previous = state.undo.pop();
  loadSnapshot(previous);
}

function redo() {
  if (!state.redo.length) return;
  state.undo.push(snapshot());
  loadSnapshot(state.redo.pop());
}

function loadSnapshot(text) {
  state.boxes = JSON.parse(text);
  state.selected = -1;
  drawOverlay();
  renderHeader();
  markDirty();
}

async function save(reviewState) {
  const frame = currentFrame();
  if (!frame) return false;
  if (state.dirty) {
    // remember progress even if the user is only passing through
    fetch('/api/in_progress', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image_id: frame.image_id }),
    }).catch(() => {});
  }
  const body = {
    image_id: frame.image_id,
    review_state: reviewState,
    objects: state.boxes.map((b) => ({ class_id: b.class_id, bbox_xyxy: b.bbox_xyxy })),
  };
  let payload;
  try {
    const response = await fetch('/api/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    payload = await response.json();
  } catch (error) {
    showToast('SAVE FAILED (network)\n' + error.message, 'err', 8000);
    return false;
  }
  if (!payload.ok) {
    showToast('SAVE FAILED\n' + payload.error, 'err', 9000);
    return false;
  }

  // Re-render strictly from the file that was just written.
  const saved = payload.record;
  const before = state.boxes.map((b) => [...b.bbox_xyxy]);
  state.boxes = saved.objects.map((o) => ({ ...o, bbox_xyxy: [...o.bbox_xyxy] }));
  const after = state.boxes.map((b) => [...b.bbox_xyxy]);
  if (before.length === after.length) {
    for (let i = 0; i < before.length; i += 1) {
      if (boxDelta(before[i], after[i]) > 1) {
        showToast('ERROR: reloaded boxes differ from what was drawn. Stopping.', 'err', 12000);
        drawOverlay();
        return false;
      }
    }
  }
  drawOverlay();
  markClean();
  const frameRef = state.frames[state.order[state.cursor]];
  frameRef.review_state = saved.review_state;
  renderHeader();
  renderStats(payload.stats);
  showToast(
    `saved ${saved.review_state} · ${saved.objects.length} box(es) · round-trip ${payload.round_trip_error.toFixed(4)} px`,
    'ok',
  );
  return true;
}

async function saveAndNext() {
  const ok = await save('MANUAL_REVIEWED');
  if (!ok) return; // never advance after a failed save
  go(1);
}

async function markNeedsReview() {
  const ok = await save('NEEDS_REVIEW');
  if (!ok) return;
  go(1);
}

async function markEmptyReviewed() {
  if (state.boxes.length) {
    if (!confirm('This image has boxes. Mark it EMPTY and reviewed anyway?')) return;
  }
  if (!confirm('Confirm: I looked at this image myself and there is NO ball / hand / racket target.')) return;
  state.boxes = [];
  drawOverlay();
  const ok = await save('MANUAL_REVIEWED');
  if (ok) go(1);
}

/* ------------------------------------------------------------------- input */

function stagePoint(event) {
  const rect = stage.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function hitTest(point) {
  if (!state.view || state.qaMode) return null;
  // handles of the selected box win over everything else
  if (state.selected >= 0) {
    const box = state.boxes[state.selected];
    for (const handle of HANDLES) {
      const hp = handlePoint(state.view, box.bbox_xyxy, handle);
      if (Math.abs(hp.x - point.x) <= HANDLE_HIT && Math.abs(hp.y - point.y) <= HANDLE_HIT) {
        return { kind: 'resize', handle, index: state.selected };
      }
    }
  }
  for (let i = state.boxes.length - 1; i >= 0; i -= 1) {
    const [x1, y1, x2, y2] = state.boxes[i].bbox_xyxy;
    const a = imageToDisplay(state.view, x1, y1);
    const b = imageToDisplay(state.view, x2, y2);
    if (point.x >= a.x && point.x <= b.x && point.y >= a.y && point.y <= b.y) {
      return { kind: 'move', index: i };
    }
  }
  return null;
}

capture.addEventListener('pointerdown', (event) => {
  if (!state.view || !currentFrame()) return;
  if (state.qaMode) { showToast('QA 模式下不能修改 bbox（按 Q 退出）', 'info'); return; }
  capture.setPointerCapture(event.pointerId);
  const point = stagePoint(event);
  const image = displayToImage(state.view, point.x, point.y);

  if (event.button === 1 || event.shiftKey || event.getModifierState?.(' ')) {
    drag = { kind: 'pan', startX: point.x, startY: point.y, panX: state.pan.x, panY: state.pan.y };
    return;
  }
  const hit = hitTest(point);
  if (hit) {
    state.selected = hit.index;
    pushUndo();
    if (hit.kind === 'move') {
      const box = state.boxes[hit.index];
      drag = {
        kind: 'move', index: hit.index, startImage: image,
        origin: [...box.bbox_xyxy],
      };
    } else {
      drag = { kind: 'resize', index: hit.index, handle: hit.handle };
    }
    drawOverlay();
    return;
  }
  // empty space: start a brand new box
  pushUndo();
  state.boxes.push({ class_id: state.activeClass, bbox_xyxy: [image.x, image.y, image.x, image.y] });
  state.selected = state.boxes.length - 1;
  drag = { kind: 'draw', index: state.selected, anchor: image };
});

capture.addEventListener('pointermove', (event) => {
  if (!drag || !state.view) return;
  const point = stagePoint(event);
  const image = displayToImage(state.view, point.x, point.y);
  if (drag.kind === 'pan') {
    const scale = state.view.scale;
    state.pan = { x: drag.panX - (point.x - drag.startX) / scale, y: drag.panY - (point.y - drag.startY) / scale };
    layout();
    return;
  }
  if (drag.kind === 'draw') {
    state.boxes[drag.index].bbox_xyxy = normalizeBox(
      state.view, drag.anchor.x, drag.anchor.y, image.x, image.y,
    );
  } else if (drag.kind === 'move') {
    const dx = image.x - drag.startImage.x;
    const dy = image.y - drag.startImage.y;
    const [x1, y1, x2, y2] = drag.origin;
    state.boxes[drag.index].bbox_xyxy = normalizeBox(
      state.view, x1 + dx, y1 + dy, x2 + dx, y2 + dy,
    );
  } else if (drag.kind === 'resize') {
    state.boxes[drag.index].bbox_xyxy = resizeBox(
      state.boxes[drag.index].bbox_xyxy, drag.handle, image.x, image.y, state.view,
    );
  }
  drawOverlay();
  renderHeader();
});

capture.addEventListener('pointerup', (event) => {
  if (!drag) return;
  const wasDraw = drag.kind === 'draw';
  const index = drag.index;
  drag = null;
  if (wasDraw && index !== undefined) {
    const box = state.boxes[index];
    if (!isValidBox(box.bbox_xyxy, state.natural)) {
      state.boxes.splice(index, 1);
      state.selected = -1;
      showToast('这次拖动太小，已忽略', 'info');
    }
  }
  if (!state.boxes.length) state.selected = -1;
  drawOverlay();
  renderHeader();
});

capture.addEventListener('wheel', (event) => {
  if (!state.view) return;
  event.preventDefault();
  const point = stagePoint(event);
  const before = displayToImage(state.view, point.x, point.y);
  state.zoomIndex = clamp(
    state.zoomIndex + (event.deltaY < 0 ? 1 : -1), 0, ZOOMS.length - 1,
  );
  const rect = stage.getBoundingClientRect();
  const newView = makeView(state.natural, { width: rect.width, height: rect.height }, ZOOMS[state.zoomIndex], state.pan);
  // keep the image point under the cursor stable while zooming
  state.pan = {
    x: before.x - point.x / newView.scale,
    y: before.y - point.y / newView.scale,
  };
  layout();
}, { passive: false });

window.addEventListener('keydown', (event) => {
  const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
  if (typing) return;
  const key = event.key;
  if (event.ctrlKey && key.toLowerCase() === 'z') { event.preventDefault(); undo(); return; }
  if (event.ctrlKey && key.toLowerCase() === 'y') { event.preventDefault(); redo(); return; }
  if (event.ctrlKey && key.toLowerCase() === 's') {
    event.preventDefault();
    save('MANUAL_REVIEWED').then((ok) => { if (ok) showToast('saved (只保存)', 'ok'); });
    return;
  }
  if (key === '0' || key === '1' || key === '2') { selectClass(Number(key)); return; }
  switch (key) {
    case 's': case 'S': saveAndNext(); break;
    case 'ArrowLeft': go(-1); break;
    case 'ArrowRight': go(1); break;
    case 'Delete': case 'Backspace': deleteSelected(); break;
    case '+': case '=': state.zoomIndex = clamp(state.zoomIndex + 1, 0, ZOOMS.length - 1); layout(); break;
    case '-': case '_': state.zoomIndex = clamp(state.zoomIndex - 1, 0, ZOOMS.length - 1); layout(); break;
    case 'r': case 'R': state.zoomIndex = 0; state.pan = { x: 0, y: 0 }; layout(); break;
    case 'g': case 'G': toggleGray(); break;
    case 'n': case 'N': markNeedsReview(); break;
    case 'e': case 'E': markEmptyReviewed(); break;
    case 'q': case 'Q': toggleQa(); break;
    case 'f': case 'F': toggleFullscreen(); break;
    default: break;
  }
});

function toggleGray() {
  const frame = currentFrame();
  if (!frame) return;
  state.gray = !state.gray;
  mainimg.src = mediaUrl(state.gray ? frame.gray3_path : frame.image_path);
  el('h-mode').textContent = state.gray ? '灰度显示（几何与彩色完全相同）' : '彩色显示';
}

function toggleQa() {
  state.qaMode = !state.qaMode;
  el('h-mode').textContent = state.qaMode ? 'QA 模式：只能看，不能改' : '编辑模式';
  el('btn-qa').classList.toggle('on', state.qaMode);
  drawOverlay();
  showToast(state.qaMode ? 'QA 模式开启（bbox 只读）' : 'QA 模式关闭', 'info');
}

function toggleFullscreen() {
  if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(() => {});
  else document.exitFullscreen().catch(() => {});
}

/* -------------------------------------------------------------------- wiring */

document.querySelectorAll('.clsbtn').forEach((button) => {
  button.onclick = () => selectClass(Number(button.dataset.class));
});
el('btn-undo').onclick = undo;
el('btn-redo').onclick = redo;
el('btn-del').onclick = deleteSelected;
el('btn-clear').onclick = clearAll;
el('btn-empty').onclick = markEmptyReviewed;
el('btn-save').onclick = () => save('MANUAL_REVIEWED').then((ok) => { if (ok) showToast('saved (只保存)', 'ok'); });
el('btn-savenext').onclick = saveAndNext;
el('btn-needs').onclick = markNeedsReview;
el('btn-zoomin').onclick = () => { state.zoomIndex = clamp(state.zoomIndex + 1, 0, ZOOMS.length - 1); layout(); };
el('btn-zoomout').onclick = () => { state.zoomIndex = clamp(state.zoomIndex - 1, 0, ZOOMS.length - 1); layout(); };
el('btn-zoomreset').onclick = () => { state.zoomIndex = 0; state.pan = { x: 0, y: 0 }; layout(); };
el('btn-gray').onclick = toggleGray;
el('btn-qa').onclick = toggleQa;
el('btn-continue').onclick = goToFirstUnlabeled;
el('filter').onchange = () => {
  state.filter = el('filter').value;
  rebuildOrder();
  loadFrame();
};
window.addEventListener('resize', layout);
window.addEventListener('beforeunload', (event) => {
  if (state.dirty) { event.preventDefault(); event.returnValue = 'Unsaved changes'; }
});

(async function boot() {
  await refreshState();
  rebuildOrder();
  await loadFrame();
  if (state.order.length === 0) showToast('当前过滤条件下没有图片', 'info');
})();
