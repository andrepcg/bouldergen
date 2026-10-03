'use strict';
// BoulderGen frontend: hash router + a pinch/pan wall viewer. Wall coordinates are millimetres
// (the rectified image is 1 px = 1 mm), so SVG overlays need no conversion.

const DIFF_GROUPS = [
  { name: 'Easy', codes: [24, 32, 40], color: '#4ade80' },
  { name: 'Medium', codes: [56, 64, 72], color: '#60a5fa' },
  { name: 'Hard', codes: [88, 96, 104], color: '#f87171' },
  { name: 'Foot', codes: [192, 200, 208], color: '#facc15' },
];
const TYPES = [[1, 'Jug'], [2, 'Edge'], [4, 'Crimp'], [8, 'Sloper'], [16, 'Pinch'], [32, 'Pocket'], [64, 'Crack']];
const COMPASS = [[8, '↖'], [16, '↑'], [32, '↗'], [4, '←'], [0, 'Any'], [64, '→'], [2, '↙'], [1, '↓'], [128, '↘']];
const ROLES = {
  10: { name: 'Start', color: '#4ade80' }, 40: { name: 'Hand', color: '#60a5fa' }, 50: { name: 'Foot', color: '#facc15' },
  20: { name: 'Finish', color: '#f472b6' }, 30: { name: 'Zone', color: '#c084fc' },
};
const FEET = [
  ['follow', 'Follow', 'Feet on any hold of the problem'],
  ['set', 'Set', 'Only marked foot holds for feet'],
  ['open', 'Open', 'Any hold on the wall for feet'],
  ['none', 'Campus', 'No feet'],
];
const STYLES = [['boulder', 'Boulder'], ['traverse', 'Traverse'], ['circuit', 'Circuit']];
const ENGINES = [
  ['boulderbot', 'BoulderBot', 'The original app’s algorithm. Loose and creative, sometimes reachy.'],
  ['kinematic', 'Kinematic', 'Simulates a climber of your size: every move is reachable, numbers show the hand order.'],
];

const ICONS = {
  back: '<path d="m15 18-6-6 6-6"/>',
  next: '<path d="m9 18 6-6-6-6"/>',
  play: '<path d="M7 4v16l13-8z"/>',
  pause: '<path d="M8 4v16M16 4v16"/>',
  eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  generate: '<path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22"/><path d="m18 2 4 4-4 4"/><path d="M2 6h1.9c1.5 0 2.9.9 3.6 2.2"/><path d="M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8"/><path d="m18 14 4 4-4 4"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  holds: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/>',
  setup: '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  area: '<path d="M4 9V5a1 1 0 0 1 1-1h4M15 4h4a1 1 0 0 1 1 1v4M20 15v4a1 1 0 0 1-1 1h-4M9 20H5a1 1 0 0 1-1-1v-4"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  bookmark: '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  fit: '<path d="M3 9V3h6M21 9V3h-6M3 15v6h6M21 15v6h-6"/>',
  camera: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z"/><circle cx="12" cy="13" r="3"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  pin: '<path d="M12 17v5M9 10.8V4h6v6.8l3 3.2H6z"/>',
};
const SVGNS = 'http://www.w3.org/2000/svg';
const SVG_TAGS = new Set(['svg', 'g', 'image', 'circle', 'polygon', 'rect', 'text', 'path', 'mask', 'defs', 'line']);

const app = document.getElementById('app');
const top_ = document.getElementById('top');
const tabbar = document.getElementById('tabbar');
let META = null;
let wall = null;
const gen = { problem: null, forced: {}, wallId: null };

// ---------------------------------------------------------------- helpers

function el(tag, attrs = {}, ...kids) {
  const e = SVG_TAGS.has(tag) ? document.createElementNS(SVGNS, tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'text') e.textContent = v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  e.append(...kids.flat(Infinity).filter(k => k != null && k !== false));
  return e;
}

// replaceChildren/append that skip null/false (conditional children)
const clean = kids => kids.flat(Infinity).filter(k => k != null && k !== false);
const put = (node, ...kids) => node.replaceChildren(...clean(kids));
const add = (node, ...kids) => node.append(...clean(kids));

function icon(name) {
  const s = el('svg', { viewBox: '0 0 24 24', class: 'icon', 'aria-hidden': 'true' });
  s.innerHTML = ICONS[name];
  return s;
}

async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers['Content-Type'] = 'application/json'; }
  const r = await fetch(url, opts);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { toast(data.detail || `Something went wrong (${r.status})`); throw new Error(data.detail); }
  return data;
}

let toastTimer;
function toast(msg, action) {
  const t = document.getElementById('toast');
  put(t, el('span', { text: msg }),
    action && el('button', { text: action.label, onclick: () => { t.classList.remove('show'); action.run(); } }));
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), action ? 5000 : 2600);
}

function store(key, val) {
  try {
    if (val === undefined) return JSON.parse(localStorage.getItem(key));
    localStorage.setItem(key, JSON.stringify(val));
  } catch { return null; }
}

// Modal dialog. Resolves to the input value (or true without input), or null when cancelled.
function dialog({ title, message, input, ok = 'OK', danger = false }) {
  const dlg = document.getElementById('dlg');
  const field = input != null ? el('input', { value: input, placeholder: 'Name', maxlength: 80 }) : null;
  put(dlg, el('form', { method: 'dialog', class: 'stack' },
    el('h3', { text: title }), message && el('p', { class: 'muted', text: message }), field,
    el('div', { class: 'row end' },
      el('button', { type: 'button', class: 'btn ghost', text: 'Cancel', onclick: () => dlg.close('cancel') }),
      el('button', { value: 'ok', class: `btn ${danger ? 'danger' : 'primary'}`, text: ok }))));
  dlg.showModal();
  if (field) field.select();
  return new Promise(res => dlg.addEventListener('close', () =>
    res(dlg.returnValue === 'ok' ? (field ? field.value : true) : null), { once: true }));
}

const groupOf = c => DIFF_GROUPS.find(g => g.codes.includes(c)) || DIFF_GROUPS[1];
const diffColor = c => groupOf(c).color;
const wallH = () => wall.height + (wall.kicker || 0);
const byId = () => Object.fromEntries(wall.holds.map(h => [h.id, h]));
const usable = h => h.kind !== 'volume';

function holdShape(h, attrs) {
  return h.poly ? el('polygon', { points: h.poly.map(p => p.join(',')).join(' '), ...attrs })
    : el('circle', { cx: h.x, cy: h.y, r: h.r || 40, ...attrs });
}

function gradeLabel(d, angle) {
  const { grades, grade_lo: lo, grade_hi: hi, r72 } = META;
  const clampI = i => Math.min(Math.max(i, lo), hi);
  const delta = Math.max(-90, Math.min(90, 5 * Math.round((angle - wall.ref_angle) / 5)));
  return grades[clampI(clampI(Math.round(d * 23)) + Math.round(r72[delta] || 0))];
}

function seg(options, value, onpick, cls = '') {
  return el('div', { class: `seg ${cls}`, role: 'group' }, options.map(([v, label]) => el('button', {
    type: 'button', class: v === value ? 'on' : null, 'aria-pressed': String(v === value), onclick: () => onpick(v),
  }, label)));
}

// ---------------------------------------------------------------- wall viewer: pinch / wheel zoom, pan, tap, drag, area

function createViewer(W, H, href, opts = {}) {
  const svg = el('svg', { class: 'viewer-svg' });
  svg.append(el('image', { href, x: 0, y: 0, width: W, height: H }));
  const layer = el('g');
  svg.append(layer);
  const fitBtn = el('button', { class: 'fab fit hidden', 'aria-label': 'Show whole wall', onclick: () => { z = 1; apply(); } }, icon('fit'));
  const box = el('div', { class: 'viewer' }, svg, fitBtn);
  let z = 1, cx = W / 2, cy = H / 2, cw = 1, ch = 1;
  const maxZ = opts.maxZoom || 8;

  // the viewBox always has the container's aspect ratio, so screen <-> wall mapping is a plain scale
  const view = () => {
    const r = svg.getBoundingClientRect();
    if (r.width && r.height) { cw = r.width; ch = r.height; }
    const a = cw / ch, [fw, fh] = W / H > a ? [W, W / a] : [H * a, H];
    return { w: fw / z, h: fh / z };
  };
  function apply() {
    z = Math.min(Math.max(z, 1), maxZ);
    const { w, h } = view();
    cx = w >= W ? W / 2 : Math.min(Math.max(cx, w / 2), W - w / 2);
    cy = h >= H ? H / 2 : Math.min(Math.max(cy, h / 2), H - h / 2);
    svg.setAttribute('viewBox', `${cx - w / 2} ${cy - h / 2} ${w} ${h}`);
    fitBtn.classList.toggle('hidden', z < 1.05);
    opts.onView?.(upp());
  }
  const upp = () => view().w / cw; // wall mm per screen px
  function toWall(x, y) {
    const r = svg.getBoundingClientRect(), { w, h } = view();
    return { x: cx - w / 2 + (x - r.left) / r.width * w, y: cy - h / 2 + (y - r.top) / r.height * h };
  }
  function zoomAround(p, x, y, newZ) {
    z = Math.min(Math.max(newZ, 1), maxZ);
    const r = svg.getBoundingClientRect(), { w, h } = view();
    cx = p.x - ((x - r.left) / r.width - .5) * w;
    cy = p.y - ((y - r.top) / r.height - .5) * h;
    apply();
  }
  new ResizeObserver(apply).observe(svg);

  const ptrs = new Map();
  let g = null;
  svg.addEventListener('pointerdown', e => {
    try { svg.setPointerCapture(e.pointerId); } catch { /* synthetic or already-released pointer */ }
    ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (ptrs.size === 1) {
      const handle = e.target.closest?.('.handle');
      g = { kind: handle ? 'drag' : opts.areaMode?.() ? 'area' : 'pan', x0: e.clientX, y0: e.clientY, cx0: cx, cy0: cy, moved: false, handle };
      if (g.kind === 'area') { g.start = toWall(e.clientX, e.clientY); g.rect = el('rect', { class: 'area-rect' }); svg.append(g.rect); }
    } else if (ptrs.size === 2) {
      g?.rect?.remove();
      const [a, b] = [...ptrs.values()];
      g = { kind: 'pinch', d0: Math.hypot(a.x - b.x, a.y - b.y) || 1, z0: z, anchor: toWall((a.x + b.x) / 2, (a.y + b.y) / 2), moved: true };
    }
  });
  svg.addEventListener('pointermove', e => {
    if (!ptrs.has(e.pointerId) || !g) return;
    ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (g.kind === 'pinch') {
      if (ptrs.size < 2) return;
      const [a, b] = [...ptrs.values()];
      zoomAround(g.anchor, (a.x + b.x) / 2, (a.y + b.y) / 2, g.z0 * Math.hypot(a.x - b.x, a.y - b.y) / g.d0);
      return;
    }
    if (Math.hypot(e.clientX - g.x0, e.clientY - g.y0) > 6) g.moved = true;
    if (!g.moved) return;
    const p = toWall(e.clientX, e.clientY);
    if (g.kind === 'pan') {
      const k = view().w / svg.getBoundingClientRect().width;
      cx = g.cx0 - (e.clientX - g.x0) * k; cy = g.cy0 - (e.clientY - g.y0) * k; apply();
    } else if (g.kind === 'drag') opts.onDrag?.(g.handle, p);
    else if (g.kind === 'area') {
      g.rect.setAttribute('x', Math.min(p.x, g.start.x)); g.rect.setAttribute('y', Math.min(p.y, g.start.y));
      g.rect.setAttribute('width', Math.abs(p.x - g.start.x)); g.rect.setAttribute('height', Math.abs(p.y - g.start.y));
    }
  });
  const end = e => {
    if (!ptrs.delete(e.pointerId) || !g) return;
    if (g.kind === 'pinch') {
      const rest = [...ptrs.values()][0]; // one finger left: keep panning, never a tap
      g = rest ? { kind: 'pan', x0: rest.x, y0: rest.y, cx0: cx, cy0: cy, moved: true } : null;
      return;
    }
    g.rect?.remove();
    if (g.kind === 'area' && g.moved) {
      const p = toWall(e.clientX, e.clientY);
      opts.onArea?.({ x0: Math.min(p.x, g.start.x), x1: Math.max(p.x, g.start.x), y0: Math.min(p.y, g.start.y), y1: Math.max(p.y, g.start.y) });
    } else if (!g.moved && e.type === 'pointerup' && g.kind !== 'drag') {
      const hit = document.elementFromPoint(e.clientX, e.clientY)?.closest?.('[data-id]');
      opts.onTap?.(toWall(e.clientX, e.clientY), hit?.dataset.id);
    }
    g = null;
  };
  svg.addEventListener('pointerup', end);
  svg.addEventListener('pointercancel', end);
  svg.addEventListener('wheel', e => {
    e.preventDefault();
    zoomAround(toWall(e.clientX, e.clientY), e.clientX, e.clientY, z * Math.exp(-e.deltaY * (e.ctrlKey ? .01 : .0015)));
  }, { passive: false });

  return { el: box, svg, layer, upp, refresh: apply };
}

// nearest hold to a wall point, within a finger-sized tolerance (small holds are hard to hit exactly)
function nearestHold(p, upp, holds = wall.holds) {
  let best = null, bd = Math.max(60, 26 * upp);
  for (const h of holds) {
    const d = Math.hypot(h.x - p.x, h.y - p.y) - (h.r || 40);
    if (d < bd) { bd = d; best = h; }
  }
  return best;
}

// darken the wall except the problem's holds, then draw role rings
function drawProblem(layer, problem, holds, extra = {}) {
  const list = (problem?.holds || []).filter(ph => holds[ph.id]);
  if (!list.length) return;
  const rad = h => Math.max(h.r || 40, 34) + 26;
  const id = 'm' + Math.random().toString(36).slice(2);
  layer.append(el('defs', {}, el('mask', { id },
    el('rect', { x: -1e4, y: -1e4, width: 3e4, height: 3e4, fill: '#fff' }),
    list.map(ph => el('circle', { cx: holds[ph.id].x, cy: holds[ph.id].y, r: rad(holds[ph.id]) + 10, fill: '#000' })))),
  el('rect', { class: 'dim', x: -1e4, y: -1e4, width: 3e4, height: 3e4, mask: `url(#${id})` }));
  for (const ph of list) {
    const h = holds[ph.id], c = ROLES[ph.role]?.color || '#fff';
    layer.append(el('circle', { class: 'ring-halo', cx: h.x, cy: h.y, r: rad(h) }),
      el('circle', { class: 'ring', cx: h.x, cy: h.y, r: rad(h), stroke: c }));
    if (extra.pinned?.[ph.id]) layer.append(el('circle', { class: 'pin-ring', cx: h.x, cy: h.y, r: rad(h) + 22, stroke: c }));
  }
  for (const ph of list) {
    if (!ph.n || !extra.numbers) continue;
    const h = holds[ph.id], o = rad(h) * .72;
    layer.append(el('g', { class: 'ring-num' }, el('circle', { cx: h.x + o, cy: h.y - o, r: 52 }),
      el('text', { x: h.x + o, y: h.y - o + 24, text: ph.n })));
  }
}

// ---------------------------------------------------------------- beta stick figure

const LIMB_NAMES = { LH: 'Left hand', RH: 'Right hand', LF: 'Left foot', RF: 'Right foot' };

// limb -> hold id after the first `step` moves
function limbsAt(b, step) {
  const pos = { ...b.start };
  for (const m of b.moves.slice(0, step)) pos[m.limb] = m.hold;
  return pos;
}

// two-segment limb from a to c (lengths l1, l2): returns the middle joint, bending towards `pick`.
// `flat` < 1 foreshortens the bend: knees and elbows mostly bend towards the wall, out of the picture plane.
function joint(a, c, l1, l2, pick, flat = 1) {
  const dx = c[0] - a[0], dy = c[1] - a[1], d = Math.hypot(dx, dy) || 1;
  const dd = Math.min(d, l1 + l2 - 1), along = (l1 * l1 - l2 * l2 + dd * dd) / (2 * dd);
  const h = flat * Math.sqrt(Math.max(0, l1 * l1 - along * along)), ux = dx / d, uy = dy / d;
  const bx = a[0] + ux * along, by = a[1] + uy * along;
  return pick([bx - uy * h, by + ux * h], [bx + uy * h, by - ux * h]);
}

function drawStick(layer, b, step, holds) {
  const p = b.poses?.[step];
  if (!p) return;
  const { arm, leg, torso, shoulder, hip } = b.body;
  const at = limbsAt(b, step), moved = step ? b.moves[step - 1].limb : null;
  const H = p.hip, S = p.shoulder;
  const ux = (S[0] - H[0]) / torso, uy = (S[1] - H[1]) / torso;
  let px = -uy, py = ux;
  if (px > 0) { px = -px; py = -py; } // (px, py) points to the climber's left (image left: they face the wall)
  const side = (c, w, k) => [c[0] + k * px * w, c[1] + k * py * w];
  const joints = { LH: side(S, shoulder, 1), RH: side(S, shoulder, -1), LF: side(H, hip, 1), RF: side(H, hip, -1) };
  const g = el('g', { class: 'stick' });
  const seg = (a, c, cls) => g.append(el('line', { x1: a[0], y1: a[1], x2: c[0], y2: c[1], class: cls }));
  const bone = (a, c, cls) => { seg(a, c, 'halo'); seg(a, c, cls); };
  bone(H, S, 'body');
  bone(joints.LH, joints.RH, 'body');
  bone(joints.LF, joints.RF, 'body');
  for (const limb of ['LH', 'RH', 'LF', 'RF']) {
    const hand = limb[1] === 'H', root = joints[limb], hold = holds[at[limb]];
    const campus = !b.start.LF;
    const end = hold ? [hold.x, hold.y]
      : campus ? [root[0], root[1] + leg * .9] // campus: legs hang
        : [root[0] + (limb === 'LF' ? -1 : 1) * leg * .55, root[1] + leg * .7]; // flagging: leg out to the side
    const l = (hand ? arm : leg) / 2;
    const mid = joint(root, end, l, l, hand
      ? (a, c) => (a[1] > c[1] ? a : c) // elbows point down
      : (a, c) => ((a[0] - H[0]) * (limb === 'LF' ? -1 : 1) > (c[0] - H[0]) * (limb === 'LF' ? -1 : 1) ? a : c), // knees out
      hand ? .5 : .35);
    const cls = limb === moved ? 'limb moved' : 'limb';
    bone(root, mid, cls); bone(mid, end, cls);
    g.append(el('circle', { cx: end[0], cy: end[1], r: 26, class: `contact${limb === moved ? ' moved' : ''}` }));
  }
  g.append(el('circle', { cx: S[0] + ux * torso * .36, cy: S[1] + uy * torso * .36, r: torso * .2, class: 'head' }));
  layer.append(g);
}

// ---------------------------------------------------------------- router + shell

async function route() {
  META = META || await api('GET', '/api/meta');
  const [, view, id, sub] = location.hash.split('/');
  app.replaceChildren();
  put(tabbar);
  if (view !== 'wall') {
    document.body.classList.remove('has-tabs');
    top_.replaceChildren(el('div', { class: 'brand' }, el('span', { class: 'logo', text: '◆' }), 'BoulderGen'));
    return viewHome();
  }
  wall = await api('GET', `/api/walls/${id}`);
  if (gen.wallId !== id) Object.assign(gen, { problem: null, forced: {}, wallId: id });
  const page = !wall.rect ? 'setup' : sub || 'gen';
  top_.replaceChildren(el('a', { href: '#/', class: 'iconbtn', 'aria-label': 'All walls' }, icon('back')),
    el('h1', { text: wall.name }), el('span', { id: 'status', class: 'status' }));
  document.body.classList.add('has-tabs');
  for (const [key, name, ic] of [['gen', 'Generate', 'generate'], ['problems', 'Saved', 'list'], ['holds', 'Holds', 'holds'], ['setup', 'Setup', 'setup']]) {
    const disabled = !wall.rect && key !== 'setup';
    tabbar.append(el('a', { href: disabled ? null : `#/wall/${id}/${key}`, class: `tab${key === page ? ' on' : ''}${disabled ? ' disabled' : ''}` },
      icon(ic), el('span', { text: name })));
  }
  ({ gen: viewGenerate, problems: viewProblems, holds: viewHolds, setup: viewSetup })[page]();
}
window.addEventListener('hashchange', route);
route();

function setStatus(text) {
  const s = document.getElementById('status');
  if (s) s.textContent = text;
}

// ---------------------------------------------------------------- home

async function viewHome() {
  app.className = 'page';
  const walls = await api('GET', '/api/walls');
  const file = el('input', { type: 'file', accept: 'image/*,.heic,.heif', class: 'visually-hidden', id: 'photo' });
  file.addEventListener('change', async () => {
    if (!file.files[0]) return;
    const name = await dialog({ title: 'Name this wall', input: walls.length ? '' : 'Home wall', ok: 'Upload' });
    if (name == null) { file.value = ''; return; }
    const fd = new FormData();
    fd.append('name', name || 'My wall'); fd.append('photo', file.files[0]);
    toast('Uploading photo…');
    const w = await api('POST', '/api/walls', fd);
    location.hash = `#/wall/${w.id}/setup`;
  });
  add(app,
    el('section', { class: 'hero' }, el('h2', { text: walls.length ? 'Your walls' : 'Set up your wall' }),
      el('p', { class: 'muted', text: walls.length ? 'Pick a wall to generate problems.' : 'Upload a photo of your wall. Shoot it straight on from low down, with the whole panel and kicker in frame.' })),
    el('div', { class: 'walls' },
      walls.map(w => el('a', { class: 'wallcard', href: `#/wall/${w.id}` },
        el('img', { src: w.rect || w.photo, alt: '' }),
        el('div', { class: 'wallcard-label' }, el('strong', { text: w.name }), el('span', { text: w.rect ? 'Ready' : 'Needs setup' })))),
      el('label', { class: 'wallcard add', for: 'photo' }, icon('camera'), el('strong', { text: 'Add a wall' }),
        el('span', { class: 'muted', text: 'JPEG or HEIC photo' }), file)));
}

// ---------------------------------------------------------------- setup: corners, dimensions, detection

function viewSetup() {
  app.className = 'page';
  const [pw, ph] = wall.photo_size;
  const corners = structuredClone(wall.corners);
  if (!corners.kicker) corners.kicker = [[.05 * pw, .81 * ph], [.95 * pw, .81 * ph], [.95 * pw, .9 * ph], [.05 * pw, .9 * ph]];
  const handles = [];
  const viewer = createViewer(pw, ph, wall.photo, {
    maxZoom: 12,
    onView: upp => handles.forEach(c => c.setAttribute('r', 15 * upp)),
    onDrag: (c, p) => {
      corners[c.dataset.part][c.dataset.i] = [Math.round(p.x), Math.round(p.y)];
      c.setAttribute('cx', p.x); c.setAttribute('cy', p.y); draw();
    },
  });
  const polys = { main: el('polygon', { class: 'corner-poly main' }), kicker: el('polygon', { class: 'corner-poly kicker' }) };
  viewer.layer.append(polys.main, polys.kicker);
  const draw = () => {
    for (const k in polys) polys[k].setAttribute('points', corners[k].map(p => p.join(',')).join(' '));
    polys.kicker.style.display = hasKicker() ? '' : 'none';
    handles.forEach(c => { c.style.display = c.dataset.part === 'kicker' && !hasKicker() ? 'none' : ''; });
  };
  for (const part of ['main', 'kicker']) corners[part].forEach((pt, i) => {
    const c = el('circle', { class: `handle ${part}`, cx: pt[0], cy: pt[1], r: 40, 'data-part': part, 'data-i': i });
    handles.push(c); viewer.layer.append(c);
  });

  const num = (name, label, value, unit) => el('label', { class: 'field' }, el('span', { text: label }),
    el('div', { class: 'input-unit' }, el('input', { type: 'number', name, value, inputmode: 'numeric', min: 0 }), el('i', { text: unit })));
  const form = el('form', { class: 'stack', onsubmit: e => e.preventDefault() },
    el('label', { class: 'field' }, el('span', { text: 'Wall name' }), el('input', { name: 'name', value: wall.name })),
    el('div', { class: 'grid3' }, num('width', 'Width', wall.width, 'mm'), num('height', 'Panel length', wall.height, 'mm'),
      num('kicker', 'Kicker height', wall.kicker, 'mm')),
    el('p', { class: 'hint', text: 'Measure along the wood, not the vertical rise. Set kicker to 0 if you have none.' }),
    el('div', { class: 'grid3' }, num('min', 'Min angle', wall.min_angle - 90, '°'), num('max', 'Max angle', wall.max_angle - 90, '°'),
      num('ref', 'Holds graded at', wall.ref_angle - 90, '°')),
    el('p', { class: 'hint', text: 'Degrees past vertical. Use the same min and max for a fixed-angle wall.' }));
  const hasKicker = () => Number(form.elements.kicker.value) > 0;
  form.elements.kicker.addEventListener('input', draw);
  draw();

  async function straighten() {
    const f = Object.fromEntries(new FormData(form)), n = k => Number(f[k]);
    if (!n('width') || !n('height')) return toast('Enter the wall width and panel length');
    if (wall.holds.length && !await dialog({ title: 'Re-straighten photo?', message: 'Holds are detected again from scratch, so your hold edits will be replaced.', ok: 'Re-straighten', danger: true })) return;
    const body = { name: f.name || wall.name, width: n('width'), height: n('height'), kicker: n('kicker'), corners: { main: corners.main },
      ref_angle: 90 + n('ref'), min_angle: 90 + Math.min(n('min'), n('max')), max_angle: 90 + Math.max(n('min'), n('max')) };
    if (body.kicker) body.corners.kicker = corners.kicker;
    btn.disabled = true; btn.textContent = 'Straightening…';
    try {
      await api('PUT', `/api/walls/${wall.id}`, body);
      wall = await api('POST', `/api/walls/${wall.id}/rectify`);
      toast(`Found ${wall.holds.length} holds`);
      location.hash = `#/wall/${wall.id}/holds`;
    } finally { btn.disabled = false; btn.textContent = label; }
  }
  const label = wall.rect ? 'Save & re-straighten' : 'Straighten & find holds';
  const btn = el('button', { class: 'btn primary block', type: 'button', text: label, onclick: straighten });

  // detection sensitivity
  const params = { ...META.detect_defaults, ...wall.detect_params };
  const sliders = [['s_thr', 'Colour saturation', 30, 200], ['v_thr', 'Colour brightness', 20, 200],
    ['white_contrast', 'White / grey contrast', 15, 120], ['dark_contrast', 'Black hold contrast', 10, 100],
    ['min_area', 'Smallest hold (mm²)', 300, 6000]].map(([k, l, min, max]) => {
      const out = el('output', { text: params[k] });
      return el('label', { class: 'field' }, el('span', {}, l, out), el('input', {
        type: 'range', min, max, value: params[k], oninput: e => { params[k] = Number(e.target.value); out.textContent = e.target.value; },
      }));
    });

  add(app,
    el('section', { class: 'card' }, el('div', { class: 'step' }, el('b', { text: '1' }), el('div', {},
      el('h3', { text: 'Mark the corners' }),
      el('p', { class: 'muted' }, 'Drag the ', el('em', { class: 'c-main', text: 'green' }), ' dots onto the main panel corners and the ',
        el('em', { class: 'c-kicker', text: 'yellow' }), ' dots onto the kicker. Pinch to zoom in for precision.'))),
    el('div', { class: 'viewer-frame' }, viewer.el)),
    el('section', { class: 'card' }, el('div', { class: 'step' }, el('b', { text: '2' }), el('div', {},
      el('h3', { text: 'Wall dimensions' }), el('p', { class: 'muted', text: 'Used to straighten the photo and turn it into real distances.' }))), form),
    el('div', { class: 'sticky-action' }, btn),
    wall.rect && el('details', { class: 'card' }, el('summary', { text: 'Detection sensitivity' }),
      el('p', { class: 'muted', text: 'Lower values find more holds, and more false positives. Re-detecting replaces all hold edits.' }),
      sliders, el('button', {
        class: 'btn', type: 'button', text: 'Re-detect holds', onclick: async () => {
          if (!await dialog({ title: 'Re-detect holds?', message: 'All hold edits will be replaced.', ok: 'Re-detect', danger: true })) return;
          wall = await api('POST', `/api/walls/${wall.id}/detect`, params);
          toast(`Found ${wall.holds.length} holds`);
        },
      })),
    el('section', { class: 'card danger-zone' }, el('h3', { text: 'Delete wall' }),
      el('p', { class: 'muted', text: 'Removes the photo, holds and every saved problem.' }),
      el('button', {
        class: 'btn danger', type: 'button', text: 'Delete this wall', onclick: async () => {
          if (!await dialog({ title: `Delete “${wall.name}”?`, message: 'This cannot be undone.', ok: 'Delete', danger: true })) return;
          await api('DELETE', `/api/walls/${wall.id}`); location.hash = '#/';
        },
      })));
  viewer.refresh();
}

// ---------------------------------------------------------------- hold editor: tap to select, panel edits the selection

function viewHolds() {
  app.className = 'stage';
  const selected = new Set();
  let armed = null; // 'add' | 'area'
  let tab = 'difficulty';
  let saveTimer;
  const viewer = createViewer(wall.width, wallH(), wall.rect, {
    areaMode: () => armed === 'area',
    onTap: (p, id) => {
      if (armed === 'add') {
        const h = { id: 'm' + Date.now().toString(36), x: Math.round(p.x), y: Math.round(p.y), r: 45, color: 'manual', kind: 'hold',
          difficulty: p.y > wall.height ? 200 : 64, type: 2, direction: 1 };
        wall.holds.push(h);
        armed = null; selected.clear(); selected.add(h.id);
        save(); return render();
      }
      const h = id ? wall.holds.find(x => x.id === id) : nearestHold(p, viewer.upp());
      if (!h) { if (selected.size) { selected.clear(); render(); } return; }
      selected.has(h.id) ? selected.delete(h.id) : selected.add(h.id);
      render();
    },
    onArea: r => {
      armed = null;
      wall.holds.filter(h => h.x >= r.x0 && h.x <= r.x1 && h.y >= r.y0 && h.y <= r.y1).forEach(h => selected.add(h.id));
      render();
    },
  });
  const panel = el('section', { class: 'panel fixed' });
  const tools = el('div', { class: 'viewer-tools' });
  viewer.el.append(tools);

  function save() {
    setStatus('Saving…');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(async () => {
      await api('PUT', `/api/walls/${wall.id}`, { holds: wall.holds });
      setStatus('Saved');
    }, 500);
  }

  function drawHolds() {
    viewer.layer.replaceChildren();
    for (const h of wall.holds) {
      const vol = !usable(h);
      const g = el('g', { 'data-id': h.id, class: `hold${selected.has(h.id) ? ' sel' : ''}${vol ? ' vol' : ''}`, style: `--c:${vol ? '#9ca3af' : diffColor(h.difficulty)}` });
      g.append(holdShape(h, {}));
      const typeTag = h.type !== 2 ? (TYPES.find(t => t[0] === h.type)?.[1] || '')[0] : '';
      const dirTag = h.direction !== 1 ? (h.direction === 0 ? '✱' : COMPASS.find(c => c[0] === h.direction)?.[1] || '') : '';
      if ((typeTag || dirTag) && !vol) g.append(el('text', { x: h.x, y: h.y + 14, text: typeTag + dirTag }));
      viewer.layer.append(g);
    }
  }

  function drawTools() {
    put(tools,
      el('button', { class: `chip-btn${armed === 'add' ? ' on' : ''}`, onclick: () => { armed = armed === 'add' ? null : 'add'; render(); } }, icon('plus'), 'Add hold'),
      el('button', { class: `chip-btn${armed === 'area' ? ' on' : ''}`, onclick: () => { armed = armed === 'area' ? null : 'area'; render(); } }, icon('area'), 'Select area'));
    if (armed) tools.append(el('div', { class: 'armed-hint', text: armed === 'add' ? 'Tap where the missing hold is' : 'Drag a box around holds' }));
  }

  function common(key) {
    const vals = new Set([...selected].map(id => wall.holds.find(h => h.id === id)?.[key]));
    return vals.size === 1 ? [...vals][0] : undefined;
  }
  function setAll(fn) {
    for (const h of wall.holds) if (selected.has(h.id)) fn(h);
    save(); render();
  }

  function drawPanel() {
    if (!selected.size) {
      const holds = wall.holds.filter(usable);
      put(panel,
        el('div', { class: 'panel-head' }, el('h3', { text: `${holds.length} holds` }),
          el('span', { class: 'muted', text: `${holds.filter(h => h.difficulty >= 192).length} feet · ${wall.holds.length - holds.length} volumes` })),
        el('p', { class: 'muted', text: 'Tap a hold to edit it. Tap more holds, or use Select area, to edit several at once.' }),
        el('p', { class: 'muted', text: 'Pinch to zoom. Missed a hold? Use Add hold.' }),
        el('div', { class: 'legend' }, DIFF_GROUPS.map(g => el('span', { style: `--c:${g.color}`, text: g.name })),
          el('span', { class: 'vol', style: '--c:#9ca3af', text: 'Volume' })));
      return;
    }
    const diff = common('difficulty'), grp = diff != null ? groupOf(diff) : null;
    const n = selected.size;
    const remove = () => {
      const removed = wall.holds.filter(h => selected.has(h.id));
      wall.holds = wall.holds.filter(h => !selected.has(h.id));
      selected.clear(); save(); render();
      toast(`Deleted ${removed.length} hold${removed.length > 1 ? 's' : ''}`, { label: 'Undo', run: () => { wall.holds.push(...removed); save(); render(); } });
    };
    const sections = {
      difficulty: () => [
        seg(DIFF_GROUPS.map(g => [g.name, el('span', { class: 'dot-label', style: `--c:${g.color}` }, g.name)]), grp?.name,
          name => setAll(h => { h.difficulty = DIFF_GROUPS.find(g => g.name === name).codes[1]; }), 'diff'),
        seg([[0, 'Easier'], [1, 'Normal'], [2, 'Harder']], grp ? grp.codes.indexOf(diff) : -1,
          i => setAll(h => { h.difficulty = groupOf(h.difficulty).codes[i]; }), 'fine'),
        el('p', { class: 'hint', text: 'Fine-tune within the level, e.g. a good crimp is “Hard · Easier”.' })],
      type: () => [
        el('div', { class: 'chips' }, TYPES.map(([v, l]) => el('button', {
          class: `chip${common('type') === v ? ' on' : ''}`, text: l, onclick: () => setAll(h => { h.type = v; h.kind = 'hold'; }),
        })), el('button', {
          class: `chip vol${common('kind') === 'volume' ? ' on' : ''}`, text: 'Volume',
          onclick: () => setAll(h => { h.kind = h.kind === 'volume' ? 'hold' : 'volume'; }),
        })),
        el('p', { class: 'hint', text: 'Volumes are drawn on the wall but never used in problems.' })],
      direction: () => [el('div', { class: 'dir-row' },
        el('div', { class: 'compass' }, COMPASS.map(([v, l]) => el('button', {
          class: common('direction') === v ? 'on' : null, text: l, 'aria-label': v ? `Pull ${l}` : 'Any direction', onclick: () => setAll(h => { h.direction = v; }),
        }))),
        el('p', { class: 'hint' }, 'The way you pull on the hold. ↓ is a normal hold, ↑ an undercling, ← and → sidepulls.'))],
    };
    put(panel,
      el('div', { class: 'panel-head' }, el('h3', { text: n === 1 ? '1 hold selected' : `${n} holds selected` }),
        el('div', { class: 'row' },
          el('button', { class: 'iconbtn danger', 'aria-label': 'Delete selected', onclick: remove }, icon('trash')),
          el('button', { class: 'btn ghost small', onclick: () => { selected.clear(); render(); } }, icon('check'), 'Done'))),
      seg([['difficulty', 'Difficulty'], ['type', 'Type'], ['direction', 'Direction']], tab, t => { tab = t; drawPanel(); }, 'tabs'),
      el('div', { class: 'section' }, sections[tab]()));
  }

  function render() { drawHolds(); drawTools(); drawPanel(); }
  add(app, viewer.el, panel);
  viewer.refresh();
  render();
}

// ---------------------------------------------------------------- generate

function viewGenerate() {
  app.className = 'stage';
  const holds = byId();
  const key = `settings:${wall.id}`;
  const s = Object.assign({ difficulty: .3, length: .5, span: .5, feet: 'follow', style: 'boulder', sit: false, types: [], angle: wall.ref_angle,
    engine: 'boulderbot', climber_height: 175, ape_index: 0 }, store(key) || {});
  s.angle = Math.min(Math.max(s.angle, wall.min_angle), wall.max_angle);
  let picking = null, showOptions = false, busy = false, step = 0, timer = null;
  let showBeta = false; // the beta is a spoiler: hidden until asked for
  const stop = () => { clearInterval(timer); timer = null; };
  if (gen.problem) gen.problem.holds = gen.problem.holds.filter(h => holds[h.id]);

  const viewer = createViewer(wall.width, wallH(), wall.rect, {
    onTap: (p, id) => {
      const h = (id && holds[id] && usable(holds[id])) ? holds[id] : nearestHold(p, viewer.upp(), wall.holds.filter(usable));
      picking = h && picking !== h.id ? h.id : null;
      render();
    },
  });
  const badge = el('div', { class: 'badge' });
  viewer.el.append(badge);
  const panel = el('section', { class: 'panel' });
  const roles = () => Object.fromEntries((gen.problem?.holds || []).map(h => [h.id, h.role]));

  function drawWall() {
    viewer.layer.replaceChildren();
    for (const h of wall.holds) if (usable(h)) viewer.layer.append(el('g', { 'data-id': h.id, class: 'ghold' }, holdShape(h, {})));
    drawProblem(viewer.layer, gen.problem, holds, { pinned: gen.forced, numbers: showBeta });
    if (showBeta && gen.problem?.beta?.poses) drawStick(viewer.layer, gen.problem.beta, step, holds);
    if (picking) {
      const h = holds[picking];
      viewer.layer.append(el('circle', { class: 'pick-ring', cx: h.x, cy: h.y, r: Math.max(h.r || 40, 34) + 50 }));
    }
    const p = gen.problem;
    put(badge, el('strong', { text: p?.grade || gradeLabel(s.difficulty, s.angle) }),
      wall.max_angle > wall.min_angle && el('span', { text: `${(p?.angle ?? s.angle) - 90}°` }),
      p && el('span', { text: `${p.holds.length} holds` }),
      el('span', { text: (ENGINES.find(e => e[0] === (p?.engine || s.engine)) || ENGINES[0])[1] }));
    badge.classList.toggle('ghost', !p);
  }

  function setRole(id, role) {
    gen.problem = gen.problem || { holds: [], grade: gradeLabel(s.difficulty, s.angle), angle: s.angle };
    gen.problem.holds = gen.problem.holds.filter(h => h.id !== id);
    if (role) { gen.problem.holds.push({ id, role }); gen.forced[id] = role; } else delete gen.forced[id];
    picking = null; render();
  }

  async function generate() {
    store(key, s);
    busy = true; picking = null; render();
    try {
      const body = { ...s, circuit: s.style === 'circuit', traverse: s.style === 'traverse', forced: gen.forced };
      gen.problem = await api('POST', `/api/walls/${wall.id}/generate`, body);
      gen.problem.angle = s.angle;
      gen.problem.engine = s.engine;
      stop(); step = 0; showBeta = false;
    } finally { busy = false; render(); }
  }

  async function saveProblem() {
    if (!gen.problem?.holds.length) return toast('Generate a problem first');
    const name = await dialog({ title: 'Save problem', input: gen.problem.name || '', ok: 'Save' });
    if (name == null) return;
    await api('POST', `/api/walls/${wall.id}/problems`, { ...gen.problem, name: name || gen.problem.grade || 'Problem' });
    toast('Saved to your problems');
  }

  const slider = (k, label, min, max, step, fmt) => {
    const out = el('output', { text: fmt(s[k]) });
    return el('label', { class: 'field' }, el('span', {}, label, out), el('input', {
      type: 'range', min, max, step, value: s[k],
      oninput: e => { s[k] = Number(e.target.value); out.textContent = fmt(s[k]); if (k === 'difficulty' || k === 'angle') drawWall(); },
      onchange: () => store(key, s),
    }));
  };
  const words = v => ['Very short', 'Short', 'Medium', 'Long', 'Very long'][Math.min(4, Math.floor(v * 5))];

  function drawPanel() {
    if (picking) {
      const cur = roles()[picking];
      put(panel,
        el('div', { class: 'panel-head' }, el('h3', { text: 'Use this hold as' }),
          el('button', { class: 'iconbtn', 'aria-label': 'Close', onclick: () => { picking = null; render(); } }, icon('x'))),
        el('div', { class: 'roles' }, [10, 40, 50, 20].map(r => el('button', {
          class: `role${cur === r ? ' on' : ''}`, style: `--c:${ROLES[r].color}`, onclick: () => setRole(picking, r),
        }, el('i'), ROLES[r].name)), el('button', { class: 'role remove', disabled: !cur, 'aria-label': 'Remove from problem', onclick: () => setRole(picking, null) }, icon('trash'), 'Remove')),
        el('p', { class: 'hint' }, icon('pin'), ' Holds you set here stay in place when you generate again.'));
      return;
    }
    const pins = Object.keys(gen.forced).length;
    const feet = FEET.find(f => f[0] === s.feet) || FEET[0];
    const engine = ENGINES.find(e => e[0] === s.engine) || ENGINES[0];
    const kinematic = s.engine === 'kinematic';
    if (kinematic && s.style === 'circuit') s.style = 'boulder';
    const num = (k, label, min, max) => el('label', { class: 'field' }, el('span', { text: label }),
      el('div', { class: 'input-unit' }, el('input', {
        type: 'number', inputmode: 'numeric', min, max, value: s[k],
        onchange: e => { s[k] = Number(e.target.value) || s[k]; store(key, s); },
      }), el('i', { text: 'cm' })));
    put(panel,
      slider('difficulty', 'Difficulty', 0, 1, .01, v => gradeLabel(v, s.angle)),
      showOptions && el('div', { class: 'options stack' },
        el('div', { class: 'group' }, el('label', { text: 'Engine' }),
          seg(ENGINES.map(e => [e[0], e[1]]), s.engine, v => { s.engine = v; store(key, s); drawWall(); drawPanel(); }),
          el('p', { class: 'hint', text: engine[2] })),
        kinematic && el('div', { class: 'grid2 tight' }, num('climber_height', 'Your height', 120, 220), num('ape_index', 'Ape index (span − height)', -30, 30)),
        el('div', { class: 'grid2' }, slider('length', 'Length', 0, 1, .01, words), slider('span', kinematic ? 'Move size' : 'Reach between holds', 0, 1, .01, words)),
        wall.max_angle > wall.min_angle && slider('angle', 'Wall angle', wall.min_angle, wall.max_angle, 5, v => `${v - 90}°`),
        el('div', { class: 'group' }, el('label', { text: 'Style' }),
          seg(STYLES.filter(st => !kinematic || st[0] !== 'circuit'), s.style, v => { s.style = v; store(key, s); drawPanel(); }),
          !kinematic && el('button', {
            class: `chip${s.sit ? ' on' : ''}`, text: 'Sit start',
            onclick: () => { s.sit = !s.sit; store(key, s); drawPanel(); },
          })),
        el('div', { class: 'group' }, el('label', { text: 'Feet' }), seg(FEET.map(f => [f[0], f[1]]), s.feet, v => { s.feet = v; store(key, s); drawPanel(); }),
          el('p', { class: 'hint', text: feet[2] })),
        el('div', { class: 'group' }, el('label', { text: 'Only these hold types (optional)' }),
          el('div', { class: 'chips' }, TYPES.map(([v, l]) => el('button', {
            class: `chip${s.types.includes(v) ? ' on' : ''}`, text: l,
            onclick: () => { s.types = s.types.includes(v) ? s.types.filter(x => x !== v) : [...s.types, v]; store(key, s); drawPanel(); },
          })))),
        el('div', { class: 'legend' }, Object.values(ROLES).map(r => el('span', { style: `--c:${r.color}`, text: r.name })))),
      gen.problem?.beta?.poses && (showBeta ? stepper(gen.problem.beta)
        : el('button', { class: 'beta-toggle', onclick: () => { showBeta = true; render(); } }, icon('eye'), 'Show beta')),
      pins > 0 && el('div', { class: 'pins' }, icon('pin'), `${pins} hold${pins > 1 ? 's' : ''} pinned`,
        el('button', { class: 'link', text: 'Clear', onclick: () => { gen.forced = {}; render(); } })),
      el('div', { class: 'actions' },
        el('button', { class: `iconbtn big${showOptions ? ' on' : ''}`, 'aria-label': 'Options', 'aria-expanded': String(showOptions),
          onclick: () => { showOptions = !showOptions; drawPanel(); } }, icon('sliders')),
        el('button', { class: 'btn primary grow', disabled: busy, onclick: generate }, icon('generate'), busy ? 'Generating…' : gen.problem ? 'Generate another' : 'Generate'),
        el('button', { class: 'iconbtn big', 'aria-label': 'Save problem', disabled: !gen.problem?.holds.length, onclick: saveProblem }, icon('bookmark'))));
  }

  function stepper(b) {
    const n = b.moves.length, m = b.moves[step - 1];
    const go = i => { step = Math.max(0, Math.min(n, i)); render(); };
    const r = roles(), nums = Object.fromEntries((gen.problem.holds || []).filter(h => h.n).map(h => [h.id, h.n]));
    const where = m && (r[m.hold] === 20 ? 'the finish' : nums[m.hold] ? `hold ${nums[m.hold]}` : m.limb[1] === 'F' ? 'a foothold' : 'a start hold');
    const what = m && (m.hold ? `${LIMB_NAMES[m.limb]} to ${where}` : `${LIMB_NAMES[m.limb]} off, flagging`);
    const load = b.poses[step]?.load;
    return el('div', { class: 'stepper' },
      el('button', { class: 'iconbtn', 'aria-label': 'Previous move', disabled: step === 0, onclick: () => { stop(); go(step - 1); } }, icon('back')),
      el('div', { class: 'step-label' },
        el('strong', { text: step ? `Move ${step} of ${n}` : 'Start position' }),
        el('span', { class: 'muted', text: `${step ? what : 'Hands on the start, feet low'}${load != null ? ` · hands ${Math.round(load * 100)}%` : ''}` })),
      el('button', { class: 'iconbtn', 'aria-label': 'Next move', disabled: step === n, onclick: () => { stop(); go(step + 1); } }, icon('next')),
      el('button', {
        class: 'iconbtn play', 'aria-label': timer ? 'Pause' : 'Play beta', onclick: () => {
          if (timer) { stop(); return render(); }
          if (step === n) step = 0;
          timer = setInterval(() => {
            if (!viewer.el.isConnected || step >= n) { stop(); if (viewer.el.isConnected) render(); return; }
            go(step + 1);
          }, 900);
          render();
        },
      }, icon(timer ? 'pause' : 'play')),
      el('button', { class: 'iconbtn', 'aria-label': 'Hide beta', onclick: () => { stop(); showBeta = false; step = 0; render(); } }, icon('x')));
  }

  function render() { drawWall(); drawPanel(); }
  add(app, viewer.el, panel);
  viewer.refresh();
  render();
}

// ---------------------------------------------------------------- saved problems

function problemThumb(p, holds) {
  const list = p.holds.filter(h => holds[h.id]).map(h => holds[h.id]);
  if (!list.length) return el('div', { class: 'thumb' });
  const pad = 250;
  const x0 = Math.min(...list.map(h => h.x)) - pad, x1 = Math.max(...list.map(h => h.x)) + pad;
  const y0 = Math.min(...list.map(h => h.y)) - pad, y1 = Math.max(...list.map(h => h.y)) + pad;
  const size = Math.max(x1 - x0, y1 - y0), mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
  const svg = el('svg', { class: 'thumb', viewBox: `${mx - size / 2} ${my - size / 2} ${size} ${size}` },
    el('image', { href: wall.rect, x: 0, y: 0, width: wall.width, height: wallH() }));
  const layer = el('g');
  svg.append(layer);
  drawProblem(layer, p, holds);
  return svg;
}

async function viewProblems() {
  app.className = 'page';
  const problems = await api('GET', `/api/walls/${wall.id}/problems`);
  const holds = byId();
  const filter = el('input', { type: 'search', placeholder: 'Search by name or grade', class: 'search' });
  const list = el('div', { class: 'problems' });
  const draw = () => {
    const q = filter.value.toLowerCase();
    const shown = problems.filter(p => `${p.name} ${p.grade}`.toLowerCase().includes(q));
    put(list, ...shown.map(p => el('article', { class: 'problem' },
      el('button', { class: 'problem-open', onclick: () => { gen.problem = structuredClone(p); gen.forced = {}; location.hash = `#/wall/${wall.id}/gen`; } },
        problemThumb(p, holds),
        el('div', { class: 'problem-info' }, el('strong', { text: p.name }),
          el('div', { class: 'meta' }, p.grade && el('span', { class: 'grade', text: p.grade }),
            el('span', { text: `${p.angle - 90}°` }), el('span', { text: new Date(p.created * 1000).toLocaleDateString() })))),
      el('button', {
        class: 'iconbtn', 'aria-label': `Delete ${p.name}`, onclick: async () => {
          if (!await dialog({ title: `Delete “${p.name}”?`, ok: 'Delete', danger: true })) return;
          await api('DELETE', `/api/problems/${p.id}`); problems.splice(problems.indexOf(p), 1); draw();
        },
      }, icon('trash')))));
    if (!shown.length) list.append(el('div', { class: 'empty' }, icon('bookmark'),
      el('p', { text: problems.length ? 'No problems match.' : 'No saved problems yet. Generate one and tap the bookmark to keep it.' })));
  };
  filter.addEventListener('input', draw);
  add(app, problems.length > 3 ? filter : null, list);
  draw();
}
