"""Problem generator: a port of the BoulderBot photo-wall engine (see boulderbot-research.md, § refs below).

Input holds are in mm on the rectified wall image: x right, y down, main panel on top, kicker stacked below.
Planner works in mm (§4-5), sequencer in metres (§6-8).
"""
import math
import random
import time
from collections import defaultdict

# ---------------------------------------------------------------- tables §2-3

GEN_HD = {24: 0, 32: .125, 40: .25, 56: .375, 64: .5, 72: .675, 88: .75, 96: .875, 104: 1,
          192: .125, 200: .5, 208: .875}  # 72 -> .675 kept (§11.1)
PLAN_D = {24: .05, 32: .10, 40: .15, 56: .20, 64: .30, 72: .40, 96: .60, 104: .70,
          192: .80, 200: .85, 208: .90}  # 88 falls through to .5 (§11.2)
UP, LEFT, DOWN, RIGHT = 56, 14, 131, 224
ROLE_START, ROLE_FINISH, ROLE_ZONE, ROLE_HAND, ROLE_FOOT = 10, 20, 30, 40, 50
FEET_MODES = {'follow': 0, 'set': 2, 'open': 4, 'none': 8}

# (code, font, V, planner target difficulty)
GRADES = [(72, '3', 'VB', 0), (96, '4', 'V0', .05), (120, '5A', 'V1', .10), (128, '5B', 'V1', .12),
          (136, '5C', 'V2', .15), (144, '6A', 'V3', .20), (148, '6A+', 'V3', .25), (152, '6B', 'V4', .30),
          (156, '6B+', 'V4', .33), (160, '6C', 'V5', .36), (164, '6C+', 'V5', .40), (168, '7A', 'V6', .45),
          (172, '7A+', 'V7', .50), (176, '7B', 'V8', .55), (180, '7B+', 'V8', .63), (184, '7C', 'V9', .66),
          (188, '7C+', 'V10', .70), (192, '8A', 'V11', .72), (196, '8A+', 'V12', .74), (200, '8B', 'V13', .76),
          (204, '8B+', 'V14', .78), (208, '8C', 'V15', .80), (212, '8C+', 'V16', .82), (216, '9A', 'V17', .84)]
GRADE_LO, GRADE_HI = 1, 18  # 4 .. 8A+
# angle delta (deg, step 5) -> grade index shift (§3)
R72 = dict(zip(range(-90, 95, 5), [-10, -9.55, -9, -8.55, -8, -7.55, -7, -6.55, -6, -5.55, -5, -4.55, -4.38, -3.92,
                                   -3.35, -3, -2.07, -1.14, 0, .61, 1.53, 2.3, 3.27, 4, 5, 5.5, 6, 6.5, 7, 7.5, 8,
                                   8.5, 9, 9.5, 10, 10.5, 11]))


def jround(v):  # Java Math.round (half up), not banker's rounding
    return int(math.floor(v + .5))


def clamp(v, lo=0., hi=1.):
    return max(lo, min(hi, v))


def is_foot(code):
    return 192 <= code <= 208


def l2z(code):
    return jround(PLAN_D.get(code, .5) * 255) / 255


def grade_index(d):
    return min(max(jround(clamp(d) * 23), GRADE_LO), GRADE_HI)


def grade_label(idx):
    _, font, v, _ = GRADES[min(max(idx, GRADE_LO), GRADE_HI)]
    return f'{font} / {v}'


def adjust_for_angle(d, angle, ref):
    """-> (difficulty used for picking, displayed grade index). Angles in 90 (vertical)..180 (roof)."""
    delta = max(-90, min(90, 5 * jround((angle - ref) / 5)))
    return clamp(d - .2 * (angle - ref) / 40), grade_index(d) + jround(R72[delta])


# ---------------------------------------------------------------- neural nets §8

ACT = {100: math.tanh, 111: lambda v: 1. if v > 0 else 0., 320: lambda v: max(0., v),
       600: lambda v: 1 / (1 + math.exp(-max(-500., min(500., v)))), 810: lambda v: v,
       811: lambda v: math.log1p(math.exp(-abs(v))) + max(v, 0.)}

NETS = {
    'A': ([[[-10, 10], [7.296841850760454, -10], [0, 0]],
           [[-10, -1.5854522686571235, -1.5048857636634352], [1.5337423897395468, 3.953566595898582, -3.2471751548709413], [0, 0, 0]],
           [[10, -2.207778986783807, 0], [0, 0, 0]]],
          [[810, 810], [111, 810, 810], [111, 111, 810], [600]]),
    'B': ([[[0.3483273715045546, -10, -4.692557621897737, 2.23190094269267], [0, -4.731169604714214, 2.945578232621898, 6.098418280140571], [-10, -6.320810288220004, 0, -7.688058198456243], [0, 0, 0, 0]],
           [[5.437875042634489, -10, 0, 5.528494215877817], [-10, 0, -3.0408353528769645, 10], [-9.219721548948856, -2.018733707374574, 10, -10], [0, 0, 0, 0]],
           [[7.848287820974292, -10, -10, 10], [0, 0, 0, 0]]],
          [[320, 320, 100, 810], [810, 600, 100, 810], [111, 100, 320, 810], [600]]),
    'C': ([[[-0.37146900130988364, -7.080198506947194, 10, -6.361165078296614, -6.117606523511805, 8.53856768872124, 7.755924594288464, 10, 8.428974079698087, -4.877199971928732, 8.299436152637277, 0],
            [-4.396682348477716, -8.683907880872967, 0, -6.959702725972868, 0, -4.829647421871775, -7.98359646386128, -2.5763313865692634, -8.884387412110469, 0, -6.4106049453761464, 0],
            [-5.232763858785727, 4.806706367081677, -7.266032811868557, -10, -1.1221857880206194, 8.872116520893986, 0.07716306822010743, 3.188828119871921, 6.405517504921057, 0, -10, 6.001591206746118],
            [0, -9.54252527773629, -2.5058904244251456, 0, 1.6168513407463134, 7.180858714114219, 6.253741088610005, 0, 10, 0.8711493228770681, -1.996086252739011, 3.9316403713504093],
            [-5.746476806098379, 4.175797539248688, -7.506789492658905, 0, -6.869071450862395, 0.37257466747008017, -8.949984289534703, -10, 8.107506815535151, -1.501554870999974, -10, 10],
            [-7.255123808354263, -8.6848206808998, 0, 0, 0, 0, 2.4324199967694002, 0.3445078215855588, 7.594367632376187, 3.4762703966984922, 0, -6.764759882544194],
            [9.372772465955444, 4.494374516771991, -4.3135489903716095, 0, 0.9201059141313034, 1.4919524066493235, -1.9891831115092184, -7.611622730479688, 0.7037942662336449, -6.541413084063552, -10, 7.601707106035432],
            [3.9976897915481575, -10, -8.826549285752902, -0.0039817063272415965, -8.040108985594323, 0, 2.710645394844944, -10, -0.15821012108391264, -4.64912046920543, -2.797714214700187, -2.2918733870276857],
            [-7.188245337977063, -3.9632900759032648, -5.780252501333423, 2.800450848261683, 4.849325326321063, -5.9816437856470674, -9.955073539316782, 0, -0.2364659859029743, -1.9355094133683846, -9.414950149930217, 0.865237235873618],
            [-3.6185741156566866, 2.435059312789559, -6.291189383867262, -3.3489014759015814, -9.764754815747018, 7.493011271582276, 3.80582730786179, -6.1242350796480505, -1.9653851619811522, 0, 4.95499837579375, -1.41975312267164],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]],
           [[0, 10, -0.6602611034815752, 0, 0.4199799388493548, 1.1879131487989874, -5.7282559119542125, -7.637834330186478, -4.593949683027214, 3.0279716181465854, -7.554661058317458],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]]],
          [[100, 100, 811, 320, 320, 100, 320, 100, 811, 600, 320, 810], [111, 600, 810, 320, 600, 600, 600, 320, 600, 111, 810], [111]]),
    'D': ([[[4.996103394679435, -10, 10, -10, -2.9523394237592395, -1.4641649220139066, 2.5165080379227787, -6.536813977098224, 2.3942030089294217, -3.9583240458784434, 4.303306782041423],
            [-0.3069117579433993, 0, -10, -6.954837509330643, 0.9202763677350744, 10, -5.344331071087192, 1.750173792869446, 0, 1.5004835183053533, 1.737142244237142],
            [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]],
           [[10, 6.988867073341299, -8.650445660655961], [0, 0, 0]]],
          [[100, 600, 320, 100, 600, 811, 600, 810, 320, 600, 810], [811, 811, 810], [600]]),
}
NET_INPUTS = {'A': 1, 'B': 3, 'C': 11, 'D': 10}


def run_net(name, feats):
    """feats in order: 558 d, 1000492 d-hd, 557 y, 108 depthBelowTop, -33 x, 1000493 isFoot, -34 dx1, 1 dy1,
    2200 dx3, 20 dy3, 109 angle. Net A uses [557], net B [557,108,1000493], C all 11, D first 10."""
    W, acts = NETS[name]
    x = [ACT[a](f) for a, f in zip(acts[0], feats)] + [1.]
    for layer, nxt in zip(W, acts[1:]):
        x[-1] = 1.
        x = [ACT[nxt[o]](sum(xi * wi for xi, wi in zip(x, layer[o]))) for o in range(len(nxt))]
    return x[0]


# ---------------------------------------------------------------- planner §4-5 (mm)

class Node:
    __slots__ = ('id', 'x', 'y', 's', 'z', 'l2z', 'qc', 'angle')


def build_graph(holds, wall, angle):
    H, K = wall['height'], wall.get('kicker', 0)
    th = math.radians(angle - 90)
    min_x = min(h['x'] for h in holds)
    nodes = {}
    for h in holds:
        n = Node()
        n.id, n.x, n.s = h['id'], h['x'] - min_x, H + K - h['y']
        if n.s <= K:  # kicker: treated as vertical
            n.y, n.z, n.angle = n.s, 0., 90
        else:
            n.y, n.z, n.angle = K + math.cos(th) * (n.s - K), math.sin(th) * (n.s - K), angle
        n.l2z = l2z(h['difficulty'])
        n.qc = n.l2z >= .8
        nodes[n.id] = n
    adj = defaultdict(dict)
    ns = list(nodes.values())
    for i, a in enumerate(ns):
        for b in ns[i + 1:]:
            dist = math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))
            if dist <= 1750:
                adj[a.id][b.id] = adj[b.id][a.id] = jround(dist)
    return nodes, adj


def region(ns, low=True):
    """Lowest (or highest) region via 250 mm cells (§5.3).
    ponytail: cells keyed by (x, surface height) instead of (x, depth z) so vertical walls work too."""
    sign = 1 if low else -1
    cells = defaultdict(list)
    for n in ns:
        cells[(int(n.x // 250), int(n.s // 250))].append(n)
    ext = {k: min(sign * n.y for n in c) for k, c in cells.items()}
    g = min(ext.values())
    out = set()
    for k, v in ext.items():
        if v == g:
            out |= {n.id for n in cells[k]}
    col = defaultdict(lambda: math.inf)
    for (cx, _), v in ext.items():
        col[cx] = min(col[cx], v)
    for cx, v in list(col.items()):
        local = min(col[c] for c in range(cx - 2, cx + 3) if c in col)
        if v - g <= 1000 and v - local <= 150:
            for k, ev in ext.items():
                if k[0] == cx and ev - v <= 75:
                    out |= {n.id for n in cells[k]}
    return out


def plan_path(nodes, adj, s, rnd):
    forced, td, circuit, L, V = s['forced'], s['target_diff'], s['circuit'], s['length'], s['variation']
    pos = {k: (n.x, n.y, n.z) for k, n in nodes.items()}

    def uia():
        return {n.id for n in nodes.values()
                if (not n.qc and abs(n.l2z - td) < .5) or (forced.get(n.id, 50) != 50 and not n.qc)}

    # §5.2 length target
    nq = [n for n in nodes.values() if not n.qc] or list(nodes.values())
    W = max(n.x for n in nq) - min(n.x for n in nq)
    D = jround(math.hypot(max(n.y for n in nq) - min(n.y for n in nq), max(n.z for n in nq) - min(n.z for n in nq)))
    base = D - 1000 if D > 2000 else D - 800
    if circuit:
        v = 2 * W + 2 * base
        rmin, rmax = min(4000, v), v
        centre = (rmin + rmax) / 2
    elif s['traverse']:
        b2 = min(2000, base)
        rmin, rmax, centre = min(1000, W), jround(math.hypot(W, b2)), W
    else:
        f = next((m for dl, wl, m in zip([3000, 5000, 8000, 10000, 12000], [3000, 3000, 4000, 5000, 8000],
                                         [1.25, 1.2, 1.15, 1.1, 1.05]) if D < dl and W < wl), 1.0)
        rmin, rmax, centre = 1000, max(jround(W * f) + base, 1000), base

    def qav(t):
        return rmin + (centre - rmin) * 2 * t if t <= .5 else centre + (rmax - centre) * (2 * t - 1)

    # §5.3 starts
    node_set = uia()
    fs = [k for k, r in forced.items() if r == 10 and k in nodes]
    if fs:
        starts = set(fs)
    else:
        ns = [nodes[k] for k in node_set]
        if not ns:
            return None
        low = region(ns)
        exp = set()
        # Sit start: those bands come out empty in BoulderBot, so the bottom 500 mm fallback is the start.
        if not s.get('sit'):
            for st in low:
                for lo_, hi_ in ((700, 1350), (600, 1600), (500, 2000)):
                    found = {e for e, c in adj[st].items() if lo_ <= c <= hi_ and not nodes[e].qc}
                    if len(found) >= 3:
                        break
                exp |= found
        if len(exp) > 3:
            starts = exp
        else:
            mh = min(n.y for n in nq)
            starts = {n.id for n in nq if n.y <= mh + 500}
        hs = [nodes[k].y for k in starts]
        hmax, hmin = max(hs), min(hs)

        def below(k):
            n = nodes[k]
            if k in starts or n.y >= hmax:
                return False
            near = sorted((c, e) for e, c in adj[k].items() if e in starts)[:3]
            return n.y <= hmin or (near and n.y < min(nodes[e].y for _, e in near))
        node_set = {k for k in node_set if not below(k)}
    fins = [k for k, r in forced.items() if r == 20 and k in nodes]
    end = rnd.choice(fins) if fins else None
    must = {k for k, r in forced.items() if r not in (10, 20) and k in nodes}
    top = region([nodes[k] for k in node_set] or nq, low=False) if end is None else None

    # §5.4
    if must - starts:
        mults = [1, 2, 4, 8, 8, 16, 16, 64, 64, 128, 256]
    elif circuit:
        mults = [1, 2, 4, 4, 4, 8, 8, 8, 16, 16, 16, 32, 32, 32]
    else:
        mults = [1, 2, 4, 8, 16]
    steep = sum(nodes[k].angle - 90 for k in node_set) / max(len(node_set), 1)
    drop_tol = next((t for lim, t in zip(range(10, 90, 10), [80, 70, 60, 50, 40, 30, 20, 15]) if steep <= lim), 10)
    LV = L - V
    xs = [nodes[k].x for k in starts]
    span = max(xs) - min(xs)
    if LV >= .7 and len(starts) >= 5 and span >= 900:
        f = .66 if span <= 3000 else .6 if span <= 4000 else .5 if span <= 5000 else .3 if span <= 8000 else 0
        m = (span - jround(span * f)) / 2
        starts = {k for k in starts if nodes[k].x <= min(xs) + m or nodes[k].x >= max(xs) - m} or starts
    nx = [nodes[k].x for k in node_set] or [0]
    first_filter = not circuit and LV >= .8 and max(nx) - min(nx) <= 4000
    starts = list(starts)

    def walk(target):
        avail, prio = set(node_set), set(must)
        cur = rnd.choice(starts)
        start = cur
        avail.discard(cur)
        prio.discard(cur)
        path, cost = [cur], 0
        while True:
            if circuit and len(path) == 4:
                avail.add(start)
                avail |= {e for e in adj[start] if e in node_set and e not in path}
            cand = [(e, c) for e, c in adj[cur].items()
                    if e in avail and (e not in path or (circuit and e == start and len(path) >= 4))]
            if not cand or all(c >= 1200 for _, c in cand):
                return None
            if cost >= target or end in path:
                return cost, path
            C = []
            for flt in (lambda e, c: 500 <= c <= 1000 or (c <= 1000 and e in prio),
                        lambda e, c: c <= 1000, lambda e, c: c <= 1200):
                C = [(e, c) for e, c in cand if flt(e, c)
                     and not (first_filter and len(path) == 1 and abs(nodes[e].x - nodes[cur].x) / max(c, 1) < .3)]
                if C:
                    break
            if not C:
                return None
            ce = dict(C)
            if end in ce:
                return cost + ce[end], path + [end]
            pc = [(c, e) for e, c in C if e in prio]
            if pc:
                c, nxt = min(pc)
            elif circuit and len(path) >= 4 and start in ce and cost >= .75 * target:
                return cost + ce[start], path + [start]
            else:
                nxt, c = rnd.choice(C)
            for e, ec in adj[cur].items():  # spread the route
                if e == end or e in prio or (circuit and e == start):
                    continue
                if e not in adj[nxt] or ec <= (300 if circuit else 500) + c:
                    avail.discard(e)
            prio.discard(nxt)
            path.append(nxt)
            cost += c
            cur = nxt

    def nearest_on(a, b, t):  # point at fraction t along a->b, nearest node among common neighbours
        pa, pb = pos[a], pos[b]
        p = tuple(u + (v - u) * t for u, v in zip(pa, pb))
        cands = (set(adj[a]) & set(adj[b])) | {a, b}
        return min(cands, key=lambda k: math.dist(pos[k], p))

    def score(cost, p, lo, hi):
        sc = 0.
        if not circuit:
            sc += 3 * sum(max(0, (nodes[a].y - nodes[b].y) - drop_tol) for a, b in zip(p, p[1:]))
        if end is None and not lo <= cost <= hi:
            sc += 2 * (lo - cost if cost < lo else cost - hi)
        last = p[-1]
        if top and end is None and last not in top:
            tc = [(c, e) for e, c in adj[last].items() if e in top]
            if tc:
                c, e = min(tc)
                gap = max(nodes[e].y - nodes[last].y, 0)
            else:
                c, gap = 2000, max(sum(nodes[k].y for k in top) / len(top) - nodes[last].y, 0)
            sc += 8 * c + 3 * gap
        for w, need, tol, R in ((5, 3, .175, 400), (3, 5, .325, 500)):
            step = jround(.6 * R)
            samples, carry = [], 0.
            for a, b in zip(p, p[1:]):
                seg = math.dist(pos[a], pos[b])
                t = carry
                while t < seg:
                    samples.append(nearest_on(a, b, t / seg))
                    t += step
                carry = t - seg
            samples.append(last)
            for q in dict.fromkeys(samples):
                n = (abs(nodes[q].l2z - td) <= tol) + sum(
                    1 for e, c in adj[q].items() if c <= R and abs(nodes[e].l2z - td) <= tol)
                sc += 100 * w * max(0, need - n)
        return sc

    # §5.6
    for k in mults:
        lo = max(rmin, qav(max(LV, 0)) - 500 * k)
        hi = max(qav(min(L + V, 1)) + 500 * k, lo)
        for _ in range(3):
            cands, t0 = [], time.monotonic()
            for _ in range(500 if circuit else 100):
                r = walk(100000 if end else rnd.randint(int(lo), int(hi)))
                if not r or len(r[1]) < 2:
                    continue
                cost, p = r
                if (end and p[-1] != end) or (circuit and p[0] != p[-1]):
                    continue
                sc = score(cost, p, lo, hi)
                if sc <= 1e-4:
                    return p
                cands.append((sc, p))
                if len(cands) >= 25 or time.monotonic() - t0 >= .2:
                    break
            if cands:  # only results[0] is used downstream, so stop at the first round that yields one
                cands.sort(key=lambda c: c[0])
                return rnd.choice(cands[:5])[1]
    return None


# ---------------------------------------------------------------- sequencer §6-7 (metres)

class P:
    __slots__ = ('id', 'x', 'y', 'dt', 'hd', 'foot', 'dir', 'type')


def dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


class Pt:
    __slots__ = ('x', 'y')

    def __init__(self, x, y):
        self.x, self.y = x, y


def spacing(d):  # §9.1
    return .4 if d <= .1 else .5 if d <= .3 else .6 if d <= .5 else .75


def within(pt, items, r):  # §9.2
    return [(c, dist(c, pt)) for c in items if abs(c.x - pt.x) <= r and abs(c.y - pt.y) <= r and dist(c, pt) <= r]


DIR_F = {8: .975, 32: .975, 4: .95, 64: .95, 2: .925, 128: .925, 1: .925}
TYPE_F = {1: 1.05, 8: 1.025, 2: .975, 32: .975, 64: .975, 4: .95}


class Sequencer:
    def __init__(self, ps, s, rnd):
        self.ps, self.rnd = ps, rnd
        self.d, self.S, self.circuit = s['d'], s['span'], s['circuit']
        self.feet, self.type_sum, self.sit = s['feet_mode'], s['type_sum'], s.get('sit')
        self.set_feet = self.feet == 2

    # state
    def reset(self, exclude):
        self.avail = [p for p in self.ps if p.id not in exclude]
        self.chosen = {}  # id -> (P, role), insertion ordered

    def add(self, p, role):
        if p in self.avail:
            self.avail.remove(p)
        self.chosen[p.id] = (p, role)
        return p

    def with_role(self, *roles):
        return [p for p, r in self.chosen.values() if r in roles]

    def roulette(self, items):  # s4_.w86
        items = sorted(items, key=lambda i: -i[1])
        total = sum(w for _, w in items)
        if total <= 0:
            return self.rnd.choice(items)[0]
        r = self.rnd.uniform(0, total)
        for c, w in items:
            r -= w
            if r <= 0:
                return c
        return items[-1][0]

    def features(self, c):
        d = self.d
        f = [d, d - c.hd, c.y, c.dt, c.x, float(c.foot), 0., 0., 0., 0., 0.]
        hands = sorted((p for p, r in self.chosen.values() if r != 50), key=lambda p: dist(p, c))
        if hands:
            n1 = hands[0]
            n3 = hands[2] if len(hands) > 2 else n1  # "third nearest" quirk (§11.3)
            mx, my = (n1.x + n3.x) / 2, (n1.y + n3.y) / 2
            a = 90 - math.degrees(math.atan2(c.y - c.x, my - mx))  # y - x quirk (§11.3)
            a = (a + 180) % 360 - 180
            if a == -180:
                a = 180
            f[6:] = [c.x - n1.x, c.y - n1.y, c.x - n3.x, c.y - n3.y, a * 0.0174533]
        return f

    def nn(self, net, c):
        f = self.features(c)
        if net == 'A':
            return run_net('A', [f[2]])
        if net == 'B':
            return run_net('B', [f[2], f[3], f[5]])
        return run_net(net, f[:NET_INPUTS[net]])

    # §7
    def pick(self, role, net, pt, spaced=False):
        d, S = self.d, self.S
        cands = [p for p in self.avail if role == 50 or not p.foot]
        if not cands:
            return None
        chosen = [p for p, _ in self.chosen.values()]
        spaced_ok = None
        if spaced:
            r = spacing(d)
            spaced_ok = {c.id for c in cands if not within(c, chosen, r)}
        sfp = role == 50 and not self.with_role(40, 30, 20)
        if role == 50:
            radii = [.4, .5, 1, 1.25, 2.5, 100] if self.set_feet else [.5, 1, 1.25, 2.5, 100]
        else:
            r0 = .25 if self.circuit else 1.25 if (role == 10 and self.chosen) else .25 * d + .375
            radii = [r0] + [x for x in (.5, .75, 1.25, 2.5, 100) if x > r0]
        for r in radii:
            C = within(pt, cands, r)
            if len(C) >= 3:
                break
        else:
            C = [(c, 0.) for c in cands]
        reach = .5 * S + .5 * d + .75
        scored = []
        for c, dl in C:
            f9 = 4 if dl < .25 else 3 if dl < .375 else 2 if dl < .5 else 1 if dl < .75 else .75 if dl < 1 else .2
            w = f9 * self.f81(c, role, sfp, reach) * self.f19(c, role) * self.nn(net, c) * self.f13(c, role) * self.f67(c, role)
            scored.append((c, w))
        scored.sort(key=lambda i: -i[1])
        choice = self.roulette(scored[:8])
        if spaced_ok is not None and not self.set_feet and choice.id not in spaced_ok:
            return None
        return self.add(choice, role)

    def f81(self, c, role, sfp, reach):
        d = self.d
        N = [(o, r, dist(o, c)) for o, r in self.chosen.values() if dist(o, c) <= 1.5]
        starts = self.with_role(10)
        feet = [x for x in N if x[1] == 50]
        if any(r == 20 and dl < .5 and o.y < c.y for o, r, dl in N):
            return 1e-9
        if any(r == 20 and dl < .5 for o, r, dl in N):
            return 1e-6
        if sfp and any(st.y - c.y < .5 for st in starts):
            return 1e-6
        if sfp and len(self.with_role(50)) == 1 and any(dl < .5 for _, _, dl in feet):
            return 1e-6
        # BoulderBot's standing start: first start hold >= .75 m above the lowest hold. Sit start skips it.
        if (role == 10 and not self.chosen and c.y < .75 and not self.sit) or (role == 40 and c.y < 1.0):
            return 1e-5
        if sfp and any(r == 10 and dl < .75 for _, r, dl in N):
            return 1e-4
        if any(r == 20 and dl < 1.0 and o.y < c.y for o, r, dl in N):
            return 1e-4
        if (role == 50 and sfp and len(self.with_role(50)) < 2 and d < .6 and c.y < .8 and
                any(o.y < c.y and c.y - o.y < .5 and abs(o.x - c.x) < c.y - o.y for o, _, _ in N)):
            return 1e-4
        if sum(1 for _, _, dl in N if dl < .5) >= 3:
            return 1e-4
        if role == 40 and all(r == 20 and dl > reach for _, r, dl in N):
            return .01
        if role == 50 and any(dl < .5 for _, _, dl in feet):
            return .05
        if role != 50 and any(r == 10 and dl < .75 and c.y <= o.y for o, r, dl in N):
            return .05
        if role == 40 and all(r == 50 for _, r, _ in N):
            return .1
        if any(dl < .25 for _, _, dl in N):
            return .3
        return 1.

    def f19(self, c, role):
        dd = self.d - c.hd
        if role == 50:
            return .2 if c.hd <= .5 else .1 if dd < -.5 else .5 if dd > -.49 else 1.
        for lim, v in ((-.5, .001), (-.375, .01), (-.25, .1), (-.125, .3), (.124, 1.), (.24, .5), (.374, .2), (.49, .05)):
            if dd < lim:
                return v
        return .01

    def f13(self, c, role):
        if role == 50 or not self.type_sum:
            return 1.
        return 10. if c.type & self.type_sum else 1e-4

    def f67(self, c, role):
        if not c.dir:
            return 1.
        U, L, D, R = (c.dir & g for g in (UP, LEFT, DOWN, RIGHT))
        if role in (20, 50):
            return .75 if U else 1.25 if D else 1.
        others = sorted(((o, r) for o, r in self.chosen.values() if r not in (50, 20) and not o.foot),
                        key=lambda i: dist(i[0], c))
        if not others:
            return 1.
        n, nr = others[0]
        U2, L2, D2, R2 = (n.dir & g for g in (UP, LEFT, DOWN, RIGHT))
        dx, above = n.x - c.x, n.y - c.y > .1
        if role == 10 and nr == 10 and ((R and R2) or (L and L2)):
            return .01
        if R2 and R and dx < -.25:
            return .2
        if L2 and L and dx > .25:
            return .2
        if U and abs(dx) > .75:
            return .1
        if above and U:
            return .01
        if above and (L or R):
            return .75
        if U2 and (L or R):
            return .5
        if D2 and D:
            return 1.25
        if U2 and U:
            return .75
        return 1.

    # §6.5
    def start_feet(self, pts):
        rnd, d = self.rnd, self.d
        S2 = self.with_role(10)[:2]
        if not S2:
            return
        my, mx = sum(p.y for p in S2) / len(S2), sum(p.x for p in S2) / len(S2)
        dy = abs(S2[0].y - S2[1].y) if len(S2) > 1 else 0
        spread = 1.0 if dy > 1 else 1.2 if dy > .5 else 1.25 if dy > .25 else 1.5
        base = my - spread
        # §11.4 fixed: bitwise group test instead of equality
        if all(p.dir & LEFT for p in S2):
            ox, oy = .5, 0
        elif all(p.dir & RIGHT for p in S2):
            ox, oy = -.5, 0
        elif all(p.dir & UP for p in S2):
            ox, oy = 0, .3
        else:
            ox, oy = 0, 0
        targets = [Pt(mx + ox - rnd.uniform(.25, .75), base + oy), Pt(mx + ox + rnd.uniform(.25, .75), base + oy)]
        p1, p2 = next(((a, b) for lim, a, b in ((.1, 1, 1), (.2, 1, .5), (.3, .8, .3), (.4, .6, .1), (.5, .5, 0),
                                                (.6, .4, 0), (.7, .2, 0), (.8, .1, 0), (.9, .05, 0)) if d <= lim), (0, 0))
        if len(pts) > 1:
            ddx, ddy = abs(pts[1].x - pts[0].x), abs(pts[1].y - pts[0].y)
            slope = 0 if ddy == 0 else 10 if ddx == 0 else ddy / ddx
            if slope > 4:
                p1, p2 = 0, p2 / 4
            elif slope > 2:
                p1, p2 = p1 / 4, p2 / 2
            elif slope > 1:
                p1 /= 2
        if oy < .1:
            if rnd.random() < p1:
                targets.append(Pt(mx + ox + rnd.uniform(-.75, .75), base + rnd.uniform(.5, .75) * spread))
            if rnd.random() < p2:
                targets.append(Pt(mx + ox + rnd.uniform(-.75, .75), base + rnd.uniform(.2, .6) * spread))
        sr = spacing(d)
        chosen = [p for p, _ in self.chosen.values()]
        pool = [c for c in self.avail if not any(abs(c.x - o.x) <= sr and abs(c.y - o.y) <= sr for o in chosen)]
        for i, t in enumerate(targets):
            free = [c for c in pool if c.id not in self.chosen]
            for r in (.2, .3, .4, .5, .6, .75):
                C = within(t, free, r)
                if len(C) >= 2:
                    break
            feet = self.with_role(50)
            scored = []
            for c, dl in C:
                f1 = 2 if dl < .1 else 1.5 if dl < .2 else 1.2 if dl < .3 else 1 if dl < .4 else .75 if dl < .5 else .5
                dd = d - c.hd
                if c.foot:
                    f2 = .01 if d > .75 and c.hd < .4 else .2 if dd < -.5 else .3 if dd < -.25 else .5 if dd > .5 else .75 if dd > .25 else 1
                    f3 = .05 if c.dir == 16 else .01 if (c.dir == 8 and i == 0) or (c.dir == 32 and i == 1) else 1
                else:
                    f2 = (.01 if d > .4 and c.hd < .4 else .05 if dd < -.5 else .1 if dd < -.25 else .2 if dd < -.1
                          else .1 if dd > .5 else .2 if dd > .25 else .3 if dd > .1 else .5)
                    f3 = 1
                m = min((dist(c, f) for f in feet), default=100)
                if i == 0:
                    f4 = 1
                elif i == 1:
                    f4 = (.01 if m < .2 else .1 if m < .4 else .2 if m < .6 else 1 if m <= .9 else .5 if m <= 1.0
                          else .2 if m <= 1.2 else .05 if m <= 1.5 else .01)
                else:
                    f4 = .2 if m < .3 else .5 if m < .5 else 1
                n = sum(1 for o, _ in C if o is not c and o.y < c.y - .1 and abs(o.x - c.x) <= .15)
                if n == 0:
                    f5 = 1
                elif i > 1:
                    f5 = 2
                elif n == 1:
                    f5 = .1 if d < .5 else .5 if d < .75 else .9
                elif n <= 3:
                    f5 = .02 if d < .5 else .1 if d < .75 else .2
                else:
                    f5 = .01
                f6 = 1e-6 if c.y > my else .01 if c.y > my - .2 else 1
                scored.append((c, f1 * f2 * f3 * f4 * f5 * f6))
            if scored:
                self.add(self.roulette(scored), 50)
            elif i <= 2:
                self.pick(50, 'D', t)

    # §6.6
    def penalty(self):
        d, S, T = self.d, self.S, .5 * self.S + .5 * self.d + .75
        items = list(self.chosen.values())
        pen = 0.
        for h, role in items:
            N = sorted(((o, r, dist(o, h)) for o, r in items if o is not h), key=lambda i: i[2])
            hands = [x for x in N if x[1] != 50]
            partner = next((o for o, r, _ in N if r == role), None) if role in (10, 20) else None
            if role == 10 and not self.circuit and any(r in (40, 20, 30) and dl < .4 for _, r, dl in N):
                pen += 5
            if role == 10 and any(r in (40, 20, 30) and dl < 1 and h.y - o.y > -.1 and 3 * abs(h.y - o.y) > abs(h.x - o.x)
                                  for o, r, dl in N):
                pen += 3
            if partner and any(o is not partner and dl < .75 and 1.5 * dist(h, partner) > dl + dist(partner, o)
                               for o, _, dl in N):
                pen += 10
            if role == 20 and not self.circuit and any(r in (40, 10, 30) and dl < 1 and h.y - o.y < .1 and 3 * abs(h.y - o.y) > abs(h.x - o.x)
                                                       for o, r, dl in N):
                pen += 40
            if role == 40 and not any(dl < 1.25 * T and h.y - o.y < .1 for o, _, dl in hands[:6]):
                pen += 20
            if len(hands) >= 2 and hands[1][2] < .3:
                pen += 5
            dd = h.hd - d
            pen += (100 if dd > .79 else 25 if dd > .59 else 5 if dd > .49 else
                    20 if dd < -.79 else 2 if dd < -.59 else 1 if dd < -.49 else 0)
            k = 1 if role in (10, 20) and partner is None else 2
            if any(dl > T for _, _, dl in hands[:k]):
                pen += 20
            if self.type_sum and role != 50 and not h.type & self.type_sum:  # §11.5 fixed: bitwise
                pen += (5 if role in (10, 20) else 1) * (1 if h.type == 0 else 2)
        return pen


def resample(path, d, S, rnd):  # §6.3
    a = 2.125 - .75 * (d + S)

    def step():
        return 1 / rnd.uniform(a - .25, a + .25)
    pts = [Pt(path[0].x, path[0].y)]
    last = seg = pts[0]
    i, st = 1, step()
    while i < len(path):
        d1, d2 = dist(last, seg), dist(last, path[i])
        if d1 <= st <= d2:
            t = (st - d1) / (d2 - d1) if d2 > d1 else 0
            q = Pt(seg.x + t * (path[i].x - seg.x), seg.y + t * (path[i].y - seg.y))
            pts.append(q)
            last = seg = q
            st = step()
        else:
            seg = path[i]
            i += 1
    if len(pts) < 2 or dist(last, path[-1]) > 1 / (a + .25):
        pts.append(Pt(path[-1].x, path[-1].y))
    return pts


def generate(holds, wall, settings, seed=None):
    """holds: [{id, x, y, difficulty, type, direction, kind?}] in mm. wall: {height, kicker, ref_angle}.
    settings: {difficulty, length, span, feet, circuit, traverse, sit, types, forced{id: role}, angle}.
    -> {holds: [{id, role}], grade, penalty}"""
    rnd = random.Random(seed)
    holds = [h for h in holds if h.get('kind', 'hold') == 'hold']
    if sum(not is_foot(h['difficulty']) for h in holds) < 2:
        raise ValueError('Need at least two hand holds')
    ref = wall.get('ref_angle', 90)
    angle = settings.get('angle', ref)
    d, grade_idx = adjust_for_angle(clamp(settings.get('difficulty', .25)), angle, ref)
    circuit = bool(settings.get('circuit'))
    S = clamp(settings.get('span', .5))
    forced = {str(k): int(v) for k, v in (settings.get('forced') or {}).items()}
    ids = {h['id'] for h in holds}
    forced = {k: v for k, v in forced.items() if k in ids}
    s = {'forced': forced, 'target_diff': GRADES[grade_index(d)][3], 'circuit': circuit,
         'traverse': bool(settings.get('traverse')), 'sit': bool(settings.get('sit')),
         'length': clamp(settings.get('length', .5)),
         'variation': clamp(settings.get('variation', 0), 0, .5)}

    nodes, adj = build_graph(holds, wall, angle)
    path = plan_path(nodes, adj, s, rnd)
    if not path:
        raise ValueError('Could not find a line on this wall with these settings')

    # §6.1
    min_x, max_y, min_y = min(h['x'] for h in holds), max(h['y'] for h in holds), min(h['y'] for h in holds)
    ps, by_id = [], {}
    for h in holds:
        p = P()
        p.id, p.x, p.y, p.dt = h['id'], (h['x'] - min_x) / 1000, (max_y - h['y']) / 1000, (h['y'] - min_y) / 1000
        p.hd, p.foot = GEN_HD.get(h['difficulty'], .5), is_foot(h['difficulty'])
        p.dir, p.type = h.get('direction', 1), h.get('type', 2)
        ps.append(p)
        by_id[p.id] = p

    # §6.2
    F = dict(forced)
    if circuit:
        F = {k: v for k, v in F.items() if v != 20}
    for role in (10, 20):
        ks = [k for k, v in F.items() if v == role]
        if len(ks) > 2:
            rnd.shuffle(ks)
            keep = ks[:1]
            if rnd.random() >= .5:
                other = next((k for k in ks[1:] if dist(by_id[k], by_id[ks[0]]) <= 1.75 - .5 * d), None)
                keep += [other] if other else []
            F = {k: v for k, v in F.items() if v != role or k in keep}

    feet_mode = FEET_MODES.get(settings.get('feet', 'follow'), 0)
    type_sum = sum(int(t) for t in settings.get('types') or [])
    seq = Sequencer(ps, {'d': d, 'span': S, 'circuit': circuit, 'feet_mode': feet_mode, 'type_sum': type_sum,
                         'sit': s['sit']}, rnd)
    pts = resample([by_id[k] for k in path], d, S, rnd)
    best = None
    for _ in range(5):  # §6.4
        seq.reset(F)
        fs = [by_id[k] for k, v in F.items() if v == 10]
        ff = [by_id[k] for k, v in F.items() if v == 20]
        if fs:
            seq.add(fs[0], 10)
            start = fs[0]
        else:
            start = seq.pick(10, 'A', pts[0])
        if not circuit:
            for f in ff:
                seq.add(f, 20)
            if not ff:
                seq.pick(20, 'B', pts[-1])
        if not fs and start and (rnd.random() < .5 or start.hd - d > .25):
            seq.pick(10, 'A', pts[0])
        elif len(fs) > 1:
            seq.add(fs[1], 10)
        if feet_mode not in (4, 8):
            seq.start_feet(pts)
        if not circuit and rnd.random() < .25 and not ff:
            seq.pick(20, 'B', pts[-1])
        middle = pts[1:-1]
        for k, v in F.items():
            if v in (30, 40):
                h = seq.add(by_id[k], v)
                near = min(middle, key=lambda q: dist(q, h), default=None)
                if near and dist(near, h) < .5:
                    middle.remove(near)
        starts = seq.with_role(10)
        for k, p in enumerate(middle):
            if k == 0 and len(starts) == 2:
                a, b = sorted(st.x for st in starts)
                if a < p.x < b and any(st.y + .1 > p.y for st in starts):
                    continue
                if any(abs(st.x - p.x) < .3 and st.y + .1 > p.y for st in starts):
                    continue
            seq.pick(40, 'C', p)
        if circuit and not seq.with_role(30):
            promote_checkpoints(seq)
        fill_gaps(seq)
        if feet_mode not in (4, 8):
            extra_feet(seq)
        ok = seq.with_role(10) and (circuit or seq.with_role(20))
        pen = seq.penalty() if ok else math.inf
        if best is None or pen < best[0]:
            best = (pen, [{'id': p.id, 'role': r} for p, r in seq.chosen.values()])
        if pen == 0:
            break
    if best[0] == math.inf:
        raise ValueError('Could not place start and finish holds')
    return {'holds': best[1], 'grade': grade_label(grade_idx), 'grade_index': grade_idx, 'penalty': best[0]}


def promote_checkpoints(seq):  # §6.4 circuit checkpoints
    hands = seq.with_role(40)
    n40 = len(hands)
    if not n40:
        return
    K = 4 if n40 > 30 else 3 if n40 > 20 else 2
    stepk = n40 / (K + 1)
    w = 0 if stepk < 1 else 1 if stepk < 3 else 2 if stepk < 5 else 3 if stepk < 7 else 4
    anchors = seq.with_role(10, 20)
    for t in sorted({jround(i * stepk) for i in range(1, K + 1)}):
        window = hands[max(0, t - w):t + w + 1]
        if not window:
            continue
        best = max(window, key=lambda h: min((dist(h, a) for a in anchors), default=100))
        seq.chosen[best.id] = (best, 30)
        anchors.append(best)


def fill_gaps(seq):  # §6.4 gap filling
    d, S = seq.d, seq.S
    K = 1.1 if d <= .1 else 1.3 if d <= .2 else 1.5 if d <= .5 else 1.8
    hands = [(p, r) for p, r in seq.chosen.values() if r != 50]
    seen = set()
    for a, ra in hands:
        others = [(b, rb) for b, rb in hands if b is not a]
        if not others:
            continue
        b, rb = min(others, key=lambda i: dist(i[0], a))
        if ra == 10 and rb != 10:
            continue
        key = frozenset((a.id, b.id))
        if key in seen:
            continue
        seen.add(key)
        thr = (DIR_F.get(a.dir, 1) * DIR_F.get(b.dir, 1) * K * (.5 * S + .75) *
               TYPE_F.get(a.type, 1) * TYPE_F.get(b.type, 1))
        if dist(a, b) > thr:
            seq.pick(40, 'C', Pt((a.x + b.x) / 2, (a.y + b.y) / 2))


def extra_feet(seq):  # §6.4 extra feet
    d, S, rnd = seq.d, seq.S, seq.rnd
    for h, role in list(seq.chosen.values()):
        if role in (10, 50):
            continue
        dx, dy = {4: (.5, 0), 2: (.5, 0), 64: (-.5, 0), 128: (-.5, 0), 8: (.3, .3), 32: (-.3, .3), 16: (0, .3)}.get(h.dir, (0, 0))
        t = Pt(h.x + dx + rnd.uniform(0, .6) - .3, h.y + dy - (1.33 - .25 * d))
        r = (.4 * d + .2 if seq.set_feet else .3 * d + .4) * (S + .5)
        counted = [p for p, _ in seq.chosen.values() if not seq.set_feet or p.foot]
        if not within(t, counted, r):
            seq.pick(50, 'D', t, spaced=True)
