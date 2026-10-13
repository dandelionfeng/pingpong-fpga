const crypto = require('crypto');
const fs = require('fs');
const http = require('http');
const path = require('path');
const { chromium } = require('playwright');

const SEED = 20261011;
const FRAME_FRACTIONS = [0.08, 0.20, 0.33, 0.47, 0.60, 0.74, 0.88];
const STAGE_HINTS = [
  'ready_or_hold_candidate',
  'toss_start_candidate',
  'rising_candidate',
  'mid_high_candidate',
  'apex_candidate',
  'descending_or_racket_approach_candidate',
  'contact_or_followthrough_candidate',
];
const TARGET_SOURCE_COUNTS = { train: 32, val: 8, quick_test: 5 };

const repo = process.cwd();
const bndstt = path.join(repo, 'artifacts', 'files', 'datasets', 'BNDSTT');
const outRoot = path.join(repo, 'artifacts', 'files', 'datasets', 'BNDSTT_MVP_v1');
const mappingPath = path.join(repo, 'artifacts', 'files', 'bndstt_origin_crop_work', 'mapping_rows.json');
const auditPath = path.join(repo, 'artifacts', 'files', 'bndstt_preview_work', 'browser_media_audit.json');

function mulberry32(seed) {
  return function random() {
    let t = seed += 0x6D2B79F5;
    t = Math.imul(t ^ t >>> 15, t | 1);
    t ^= t + Math.imul(t ^ t >>> 7, t | 61);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

function shuffled(values, random) {
  const out = [...values];
  for (let i = out.length - 1; i > 0; --i) {
    const j = Math.floor(random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

function csvCell(value) {
  const text = value === null || value === undefined ? '' : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function writeCsv(file, rows, fields) {
  const lines = [fields.join(',')];
  for (const row of rows) lines.push(fields.map((field) => csvCell(row[field])).join(','));
  fs.writeFileSync(file, `\ufeff${lines.join('\n')}\n`, 'utf8');
}

function fileSha256(file) {
  const hash = crypto.createHash('sha256');
  hash.update(fs.readFileSync(file));
  return hash.digest('hex');
}

function safeName(row) {
  return `${row.session_id}__o${row.origin_clip_index}`.replace(/[^A-Za-z0-9_.-]+/g, '_');
}

function startServer(files) {
  const byId = new Map(files.map((file, index) => [String(index), file]));
  return new Promise((resolve) => {
    const server = http.createServer((request, response) => {
      const match = /^\/media\/(\d+)$/.exec(request.url || '');
      const file = match ? byId.get(match[1]) : null;
      if (!file) { response.writeHead(404); response.end(); return; }
      const size = fs.statSync(file).size;
      const headers = { 'Content-Type': 'video/mp4', 'Accept-Ranges': 'bytes', 'Access-Control-Allow-Origin': '*' };
      const parsed = /bytes=(\d+)-(\d*)/.exec(request.headers.range || '');
      if (parsed) {
        const start = Number(parsed[1]);
        const end = parsed[2] ? Math.min(Number(parsed[2]), size - 1) : size - 1;
        response.writeHead(206, { ...headers, 'Content-Range': `bytes ${start}-${end}/${size}`, 'Content-Length': end - start + 1 });
        fs.createReadStream(file, { start, end }).pipe(response);
      } else {
        response.writeHead(200, { ...headers, 'Content-Length': size });
        fs.createReadStream(file).pipe(response);
      }
    });
    server.listen(0, '127.0.0.1', () => {
      const port = server.address().port;
      resolve({ server, urls: new Map(files.map((file, index) => [file, `http://127.0.0.1:${port}/media/${index}`])) });
    });
  });
}

async function captureFrames(page, url) {
  return page.evaluate(async ({ url, fractions }) => {
    document.body.innerHTML = '';
    const video = document.createElement('video');
    video.crossOrigin = 'anonymous';
    video.muted = true;
    video.preload = 'auto';
    video.src = url;
    document.body.appendChild(video);
    const wait = (event, timeout = 15000) => new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`timeout:${event}`)), timeout);
      video.addEventListener(event, () => { clearTimeout(timer); resolve(); }, { once: true });
      video.addEventListener('error', () => { clearTimeout(timer); reject(new Error(`media_error:${video.error?.code || 'unknown'}`)); }, { once: true });
    });
    await wait('loadedmetadata');
    const result = { duration: video.duration, width: video.videoWidth, height: video.videoHeight, frames: [] };
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    for (let i = 0; i < fractions.length; ++i) {
      const fraction = fractions[i];
      const seeked = wait('seeked');
      video.currentTime = Math.min(video.duration * fraction, Math.max(0, video.duration - 0.001));
      await seeked;
      ctx.drawImage(video, 0, 0);
      const colorJpeg = canvas.toDataURL('image/jpeg', 0.95);
      const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height);
      for (let p = 0; p < pixels.data.length; p += 4) {
        const y = Math.max(0, Math.min(255, Math.round(
          0.299 * pixels.data[p] + 0.587 * pixels.data[p + 1] + 0.114 * pixels.data[p + 2]
        )));
        pixels.data[p] = y;
        pixels.data[p + 1] = y;
        pixels.data[p + 2] = y;
      }
      ctx.putImageData(pixels, 0, 0);
      const grayPng = canvas.toDataURL('image/png');
      result.frames.push({ fraction, timestamp: video.currentTime, colorJpeg, grayPng });
    }
    video.removeAttribute('src'); video.load(); video.remove();
    return result;
  }, { url, fractions: FRAME_FRACTIONS });
}

function chooseSources(rows, sessions, count, random) {
  const bySession = new Map();
  for (const session of sessions) bySession.set(session, []);
  for (const row of rows) if (bySession.has(row.session_id)) bySession.get(row.session_id).push(row);
  for (const [session, candidates] of bySession) bySession.set(session, shuffled(candidates, random));
  const picked = [];
  for (const session of shuffled(sessions, random)) {
    const candidate = bySession.get(session).shift();
    if (candidate) picked.push(candidate);
  }
  while (picked.length < count) {
    let progressed = false;
    for (const session of shuffled(sessions, random)) {
      const candidate = bySession.get(session).shift();
      if (candidate && picked.length < count) { picked.push(candidate); progressed = true; }
    }
    if (!progressed) break;
  }
  if (picked.length !== count) throw new Error(`Could only select ${picked.length}/${count} source videos`);
  return picked;
}

(async () => {
  const random = mulberry32(SEED);
  const mappingDocument = JSON.parse(fs.readFileSync(mappingPath, 'utf8'));
  const mapping = mappingDocument.rows;
  const audit = JSON.parse(fs.readFileSync(auditPath, 'utf8'));
  const auditByPath = new Map(audit.audit.map((row) => [row.path, row]));
  const candidates = mapping.filter((row) => row.origin_exists && row.origin_path && row.session_id && !row.origin_path.includes('/demo1/'));
  const uniqueByPath = new Map(candidates.map((row) => [row.origin_path, row]));
  const rows = [...uniqueByPath.values()].filter((row) => {
    const info = auditByPath.get(row.origin_path);
    return info && !info.error && info.decoded?.duration >= 0.45;
  });
  const sessions = shuffled([...new Set(rows.map((row) => row.session_id))].sort(), random);
  if (sessions.length < 15) throw new Error(`Not enough independent sessions: ${sessions.length}`);

  const quickSessions = sessions.slice(0, 5);
  const valSessions = sessions.slice(5, 10);
  const trainSessions = sessions.slice(10);
  const trainSources = chooseSources(rows, trainSessions, TARGET_SOURCE_COUNTS.train, random);
  const valSources = chooseSources(rows, valSessions, TARGET_SOURCE_COUNTS.val, random);
  const quickSources = chooseSources(rows, quickSessions, TARGET_SOURCE_COUNTS.quick_test, random);
  const selected = [
    ...trainSources.map((row) => ({ ...row, mvp_split: 'train' })),
    ...valSources.map((row) => ({ ...row, mvp_split: 'val' })),
    ...quickSources.map((row) => ({ ...row, mvp_split: 'quick_test' })),
  ];

  fs.mkdirSync(outRoot, { recursive: true });
  for (const split of ['train', 'val']) {
    fs.mkdirSync(path.join(outRoot, 'images_color', split), { recursive: true });
    fs.mkdirSync(path.join(outRoot, 'images_gray3', split), { recursive: true });
    fs.mkdirSync(path.join(outRoot, 'labels', split), { recursive: true });
  }

  const sourceRows = selected.map((row) => {
    const absolute = path.join(bndstt, ...row.origin_path.split('/'));
    const info = auditByPath.get(row.origin_path);
    return {
      source_id: row.source_id,
      session_id: row.session_id,
      split: row.mvp_split,
      source_video_path: row.origin_path,
      source_video_sha256: fileSha256(absolute),
      duration_seconds: info.decoded.duration,
      frame_count: info.structural?.video?.frame_count ?? '',
      width: info.decoded.width,
      height: info.decoded.height,
      spin_code: row.spin_code ?? '',
      landing_code: row.landing_code ?? '',
    };
  });
  writeCsv(path.join(outRoot, 'split_manifest.csv'), sourceRows, [
    'source_id', 'session_id', 'split', 'source_video_path', 'source_video_sha256',
    'duration_seconds', 'frame_count', 'width', 'height', 'spin_code', 'landing_code',
  ]);

  const frameSources = selected.filter((row) => row.mvp_split !== 'quick_test');
  const absoluteFiles = frameSources.map((row) => path.join(bndstt, ...row.origin_path.split('/')));
  const local = await startServer(absoluteFiles);
  const browser = await chromium.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
    args: ['--disable-gpu'],
  });
  const page = await browser.newPage();
  const frameRows = [];
  for (let sourceIndex = 0; sourceIndex < frameSources.length; ++sourceIndex) {
    const row = frameSources[sourceIndex];
    const absolute = absoluteFiles[sourceIndex];
    const capture = await captureFrames(page, local.urls.get(absolute));
    const info = auditByPath.get(row.origin_path);
    const sourceName = safeName(row);
    for (let i = 0; i < capture.frames.length; ++i) {
      const frame = capture.frames[i];
      const frameIndex = info.structural?.video?.frame_count
        ? Math.min(info.structural.video.frame_count - 1, Math.max(0, Math.round(frame.timestamp / capture.duration * (info.structural.video.frame_count - 1))))
        : '';
      const stem = `${sourceName}__p${String(Math.round(frame.fraction * 100)).padStart(2, '0')}__f${String(frameIndex).padStart(4, '0')}`;
      const colorRel = path.join('images_color', row.mvp_split, `${stem}.jpg`).replaceAll('\\', '/');
      const grayRel = path.join('images_gray3', row.mvp_split, `${stem}.png`).replaceAll('\\', '/');
      const labelRel = path.join('labels', row.mvp_split, `${stem}.txt`).replaceAll('\\', '/');
      const colorAbs = path.join(outRoot, ...colorRel.split('/'));
      const grayAbs = path.join(outRoot, ...grayRel.split('/'));
      fs.writeFileSync(colorAbs, Buffer.from(frame.colorJpeg.replace(/^data:image\/jpeg;base64,/, ''), 'base64'));
      fs.writeFileSync(grayAbs, Buffer.from(frame.grayPng.replace(/^data:image\/png;base64,/, ''), 'base64'));
      fs.writeFileSync(path.join(outRoot, ...labelRel.split('/')), '', 'utf8');
      frameRows.push({
        source_id: row.source_id,
        session_id: row.session_id,
        split: row.mvp_split,
        stage_hint: STAGE_HINTS[i],
        fraction: frame.fraction,
        timestamp_seconds: frame.timestamp,
        frame_index: frameIndex,
        source_video_path: row.origin_path,
        original_image_path: colorRel,
        derived_gray3_path: grayRel,
        yolo_label_path: labelRel,
        width: capture.width,
        height: capture.height,
        gray3_sha256: fileSha256(grayAbs),
        annotation_review_status: 'unreviewed',
      });
    }
    console.log(`captured ${sourceIndex + 1}/${frameSources.length} ${row.mvp_split} ${row.source_id}`);
  }
  await browser.close();
  await new Promise((resolve) => local.server.close(resolve));

  writeCsv(path.join(outRoot, 'frames_manifest.csv'), frameRows, [
    'source_id', 'session_id', 'split', 'stage_hint', 'fraction', 'timestamp_seconds', 'frame_index',
    'source_video_path', 'original_image_path', 'derived_gray3_path', 'yolo_label_path',
    'width', 'height', 'gray3_sha256', 'annotation_review_status',
  ]);
  fs.writeFileSync(path.join(outRoot, 'data.yaml'), [
    `path: ${outRoot.replaceAll('\\', '/')}`,
    'train: images_gray3/train',
    'val: images_gray3/val',
    'names:',
    '  0: ball',
    '  1: hand',
    '  2: racket',
    '',
  ].join('\n'), 'utf8');
  fs.writeFileSync(path.join(outRoot, 'dataset_summary.json'), JSON.stringify({
    name: 'bndstt_yolov8n_mvp_v1',
    status: 'PROTOTYPE / MVP',
    seed: SEED,
    source: 'J0LE/BNDSTT videos/origin only',
    classes: ['ball', 'hand', 'racket'],
    preprocessing: 'BT.601 grayscale -> replicate to 3 channels; training loader later performs 640x640 letterbox(114) and /255 once',
    session_counts: { train: trainSessions.length, val: valSessions.length, quick_test: quickSessions.length },
    source_video_counts: TARGET_SOURCE_COUNTS,
    frame_counts: { train: trainSources.length * FRAME_FRACTIONS.length, val: valSources.length * FRAME_FRACTIONS.length, total: frameRows.length },
    frame_fractions: FRAME_FRACTIONS,
    stage_hints_are_ground_truth: false,
    annotation_state: 'empty YOLO label files; manual annotation required',
  }, null, 2), 'utf8');
  console.log(JSON.stringify({ outRoot, sessions: { train: trainSessions.length, val: valSessions.length, quick_test: quickSessions.length }, sources: TARGET_SOURCE_COUNTS, frames: frameRows.length }, null, 2));
})().catch((error) => { console.error(error); process.exitCode = 1; });
