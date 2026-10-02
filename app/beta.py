"""Kinematic problem generator: weighted A* over body states (LH, RH, LF, RF).

A move relocates one limb. A state is legal only if a stick-figure body of the configured
height / ape index can hold it: feet below hands, hip reachable from both feet, shoulders
from both hands, centre of mass over the contacts, and every hand pulled in its hold's
usable direction. Coordinates: metres, x right, y up along the wall surface from the floor.
"""
import heapq
import math
import random
import time

from app.generator import FEET_MODES, GEN_HD, adjust_for_angle, clamp, grade_label, is_foot

LH, RH, LF, RF = range(4)
LIMBS = ('LH', 'RH', 'LF', 'RF')
# pull direction bit -> unit vector (x right, y up)
PULL = {b: (dx / math.hypot(dx, dy), dy / math.hypot(dx, dy)) for b, (dx, dy) in
        {1: (0, -1), 2: (-1, -1), 4: (-1, 0), 8: (-1, 1), 16: (0, 1), 32: (1, 1), 64: (1, 0), 128: (1, -1)}.items()}


class Body:
    """Segment lengths from height and ape index (wingspan - height), metres."""

    def __init__(self, height=1.75, ape=0.0):
        self.h = height
        self.wingspan = wingspan = height + ape
        self.shoulder = .115 * height                      # half shoulder width
        self.arm = (wingspan - 2 * self.shoulder) / 2 * .95  # shoulder to grip, slightly bent
        self.torso = .30 * height                          # hip to shoulder centre
        self.leg = .50 * height                            # hip to foot
        self.hip = .08 * height                            # half hip width
        self.max_hand_gap = 2 * (self.arm + self.shoulder) * .92
        self.max_foot_gap = .65 * height


class Hold:
    __slots__ = ('id', 'x', 'y', 'hd', 'dir', 'foot', 'i')


def pose(body, hands, feet):
    """(com_x, com_y, hip_x, hip_y, shoulder_x, shoulder_y) for a legal pose, or None.
    hands/feet: lists of Hold (feet may be empty)."""
    hx = sum(h.x for h in hands) / len(hands)
    hy = sum(h.y for h in hands) / len(hands)
    reach = body.arm + body.shoulder
    if not feet:  # campus: hang straight below the hands
        if any(math.hypot(h.x - hx, h.y - (hy)) > reach for h in hands):
            return None
        sy = hy - body.arm * .8
        return hx, sy - body.torso * .75, hx, sy - body.torso, hx, sy
    fx = sum(f.x for f in feet) / len(feet)
    fy = sum(f.y for f in feet) / len(feet)
    base_x = .35 * hx + .65 * fx
    base_y = fy + clamp((hy - fy) * .45, .3, body.leg * .95)
    best, best_v = None, math.inf
    for dx in (0, -.15, .15):  # ponytail: 3x3 hip search, solve the IK properly if poses look wrong
        for dy in (0, -.15, .15):
            px, py = base_x + dx, base_y + dy
            ux, uy = hx - px, hy - py
            n = math.hypot(ux, uy) or 1
            sx, sy = px + body.torso * ux / n, py + body.torso * uy / n
            v = sum(max(0, math.hypot(h.x - sx, h.y - sy) - reach) for h in hands)
            v += sum(max(0, math.hypot(f.x - px, f.y - py) - (body.leg + body.hip)) for f in feet)
            if v < best_v:
                best_v, best = v, (px + .25 * (sx - px), py + .25 * (sy - py), px, py, sx, sy)
            if v == 0:
                return best
    return best if best_v <= 1e-9 else None


def legal(body, s, holds, campus):
    """-> centre of mass if state s = (LH, RH, LF, RF) indices is climbable, else None."""
    lh, rh = holds[s[LH]], holds[s[RH]]
    hands = [lh, rh]
    feet = [] if campus else [holds[s[LF]], holds[s[RF]]]
    if math.hypot(lh.x - rh.x, lh.y - rh.y) > body.max_hand_gap:
        return None
    if feet:
        lf, rf = feet
        if s[LF] in (s[LH], s[RH]) or s[RF] in (s[LH], s[RH]):
            return None  # hand and foot sharing a hold
        if max(lf.y, rf.y) > min(lh.y, rh.y) + .05:
            return None  # feet must stay below hands
        if (lh.y + rh.y) / 2 - (lf.y + rf.y) / 2 < .5:
            return None  # too compressed
        if lf.x > rf.x + .15:
            return None  # crossed feet
        if math.hypot(lf.x - rf.x, lf.y - rf.y) > body.max_foot_gap:
            return None
    com = pose(body, hands, feet)
    if com is None:
        return None
    xs = [h.x for h in hands + feet]
    if not min(xs) - .2 <= com[0] <= max(xs) + .2:
        return None  # barn door: nothing to the side of the centre of mass
    for h in hands:
        if h.dir and h.dir in PULL:
            vx, vy = com[0] - h.x, com[1] - h.y
            n = math.hypot(vx, vy) or 1
            px, py = PULL[h.dir]
            if (vx * px + vy * py) / n < -.2:
                return None  # body on the wrong side of a sidepull / undercling
    return com


class Search:
    def __init__(self, holds, body, d, span, mode, rnd):
        self.holds, self.body, self.d, self.rnd = holds, body, d, rnd
        self.campus = mode == 8
        self.hand_ok = [not h.foot for h in holds]
        self.foot_ok = [not self.campus and (mode != 2 or h.foot) for h in holds]
        # preferred and maximum hand move: easy problems climb in small steps, hard ones stretch
        self.pref = body.arm * (.6 + .45 * d + .45 * span)
        self.max_move = self.pref * 1.35
        self.max_gap = max(self.max_move, .5 * body.wingspan)  # hands apart, no iron crosses
        self.max_lean = (.22 + .1 * d) * body.h  # hands' midpoint vs feet's midpoint, sideways
        self.noise = [rnd.uniform(0, 1.2) for _ in holds]  # variety between generations
        self.diff_cost = [4 * max(0, abs(h.hd - d) - .12) for h in holds]
        self.cache = {}
        self.near = [sorted((j for j, o in enumerate(holds) if j != i and math.hypot(o.x - h.x, o.y - h.y) < 1.9),
                            key=lambda j: math.hypot(holds[j].x - h.x, holds[j].y - h.y)) for i, h in enumerate(holds)]

    def ok(self, s):
        """Legal for the body, and within this problem's comfort limits (hand gap, sideways lean)."""
        if s not in self.cache:
            hs = self.holds
            lh, rh = hs[s[LH]], hs[s[RH]]
            com = None
            if math.hypot(lh.x - rh.x, lh.y - rh.y) <= self.max_gap and (
                    self.campus or abs((lh.x + rh.x) / 2 - (hs[s[LF]].x + hs[s[RF]].x) / 2) <= self.max_lean):
                com = legal(self.body, s, hs, self.campus)
            self.cache[s] = com
        return self.cache[s]

    def feet_options(self, s, new_hands, keep=2):
        """Feet for the next hand move: stay put, or move one or both feet first (feet up, then reach).
        Every intermediate pose must be legal. Yields up to `keep` (lf, rf, cost), best first."""
        hs, b = self.holds, self.body
        lo_hand = min(hs[new_hands[0]].y, hs[new_hands[1]].y)
        want = (hs[new_hands[0]].y + hs[new_hands[1]].y) / 2 - .57 * b.h  # comfortable stance height

        def pref(lf, rf):
            f1, f2 = hs[lf], hs[rf]
            return abs((f1.y + f2.y) / 2 - want) + .5 * abs(abs(f1.x - f2.x) - .35) + .3 * (self.noise[lf] + self.noise[rf])
        singles = {LF: [], RF: []}
        for k in (LF, RF):
            cur = hs[s[k]]
            for j in self.near[s[k]][:40]:
                c = hs[j]
                if self.foot_ok[j] and c.y <= lo_hand - .5 and math.hypot(c.x - cur.x, c.y - cur.y) <= .9:
                    singles[k].append(j)
        opts = [(pref(s[LF], s[RF]) - .3, s[LF], s[RF])]
        opts += [(pref(j, s[RF]), j, s[RF]) for j in singles[LF]]
        opts += [(pref(s[LF], j), s[LF], j) for j in singles[RF]]
        best_l = sorted(singles[LF], key=lambda j: pref(j, s[RF]))[:3]
        best_r = sorted(singles[RF], key=lambda j: pref(s[LF], j))[:3]
        opts += [(pref(l, r), l, r) for l in best_l for r in best_r]
        opts.sort()
        found = 0
        old = (s[LH], s[RH])
        for _, lf, rf in opts:
            # feet move under the old hands (left foot first), then the hand moves
            steps = [(*old, lf, s[RF]), (*old, lf, rf), (*new_hands, lf, rf)]
            if all(self.ok(st) is not None for st in steps):
                moved = (lf != s[LF]) + (rf != s[RF])
                dist = math.dist((hs[lf].x, hs[lf].y), (hs[s[LF]].x, hs[s[LF]].y)) + math.dist((hs[rf].x, hs[rf].y), (hs[s[RF]].x, hs[s[RF]].y))
                yield lf, rf, .3 * moved + .3 * dist + .2 * (self.noise[lf] * (lf != s[LF]) + self.noise[rf] * (rf != s[RF]))
                found += 1
                if found >= keep:
                    return

    def moves(self, s):
        """Compound moves: optional foot adjustments, then one hand to a new hold."""
        hs = self.holds
        for limb in (LH, RH):
            cur, other = hs[s[limb]], s[RH if limb == LH else LH]
            cands = []
            for j in self.near[s[limb]]:
                c = hs[j]
                dist = math.hypot(c.x - cur.x, c.y - cur.y)
                if not self.hand_ok[j] or c.y < cur.y - .3 or dist < .1 or dist > self.max_move:
                    continue
                over = max(0, dist - self.pref) / self.pref  # stretching hurts more than short moves
                cost = 1 + 4 * over ** 2 + .5 * ((dist - self.pref) / self.pref) ** 2 + self.diff_cost[j] + self.noise[j]
                if j == other:
                    cost += .3  # match
                lx, rx = (c.x, hs[other].x) if limb == LH else (hs[other].x, c.x)
                if lx > rx + .1 and not hs[s[LH]].x > hs[s[RH]].x + .1:
                    cost += 1.5  # crossing hands
                cands.append((cost, j))
            # ponytail: keep the 10 cheapest moves per hand; widen if good lines get missed on sparse walls
            for cost, j in sorted(cands)[:10]:
                new_hands = (j, other) if limb == LH else (other, j)
                if self.campus:
                    ns = (*new_hands, *new_hands)
                    if self.ok(ns) is not None:
                        yield ns, cost
                    continue
                for lf, rf, fcost in self.feet_options(s, new_hands):
                    yield (*new_hands, lf, rf), cost + fcost

    def run(self, start, goal, target, limit=1200, deadline=None):
        """Weighted A* from state start until goal(state). target: hold index the hands head for."""
        hs, t = self.holds, self.holds[target]

        def h(s):  # roughly the hand moves left, each costing ~1.5
            return 1.5 * sum(math.hypot(t.x - hs[s[k]].x, t.y - hs[s[k]].y) for k in (LH, RH)) / self.pref
        g = {start: 0.}
        prev = {start: None}
        heap = [(h(start), 0., start)]
        n = 0
        while heap:
            f, cost, s = heapq.heappop(heap)
            if goal(s):
                path = []
                while s is not None:
                    path.append(s)
                    s = prev[s] and prev[s][0]
                return cost, path[::-1], prev
            if cost > g.get(s, math.inf):
                continue
            n += 1
            if n > limit or (deadline and time.monotonic() > deadline):
                return None
            for ns, c in self.moves(s):
                nc = cost + c
                if nc < g.get(ns, math.inf):
                    g[ns] = nc
                    prev[ns] = (s,)
                    heapq.heappush(heap, (nc + 2 * h(ns), nc, ns))
        return None


def to_holds(holds_in, wall):
    """Wall-image mm holds -> Hold objects in metres, y up from the floor (volumes dropped)."""
    total = wall['height'] + wall.get('kicker', 0)
    holds = []
    for h in holds_in:
        if h.get('kind', 'hold') != 'hold':
            continue
        o = Hold()
        o.id, o.x, o.y = h['id'], h['x'] / 1000, (total - h['y']) / 1000
        o.hd, o.dir, o.foot = GEN_HD.get(h['difficulty'], .5), h.get('direction', 1), is_foot(h['difficulty'])
        o.i = len(holds)
        holds.append(o)
    return holds


def generate(holds_in, wall, settings, seed=None):
    """Same contract as generator.generate, plus a 'beta' list of moves."""
    rnd = random.Random(seed)
    ref = wall.get('ref_angle', 90)
    angle = settings.get('angle', ref)
    d, grade_idx = adjust_for_angle(clamp(settings.get('difficulty', .25)), angle, ref)
    span, length = clamp(settings.get('span', .5)), clamp(settings.get('length', .5))
    mode = FEET_MODES.get(settings.get('feet', 'follow'), 0)
    body = Body(clamp(float(settings.get('climber_height', 175)) / 100, 1.0, 2.2),
                clamp(float(settings.get('ape_index', 0)) / 100, -.3, .3))
    forced = {str(k): int(v) for k, v in (settings.get('forced') or {}).items()}
    if settings.get('circuit'):
        raise ValueError('Circuits are only supported by the BoulderBot engine')

    holds = to_holds(holds_in, wall)
    idx = {h.id: h.i for h in holds}
    if mode == 2:  # set feet: pinned feet count as foot holds too
        for k, r in forced.items():
            if r == 50 and k in idx:
                holds[idx[k]].foot = True
    hands = [h for h in holds if not h.foot]
    if len(hands) < 2:
        raise ValueError('Need at least two hand holds')

    deadline = time.monotonic() + 3
    best = None
    for attempt in range(8):
        if time.monotonic() > deadline:
            break
        srch = Search(holds, body, d, span, mode, rnd)
        r = attempt_once(srch, holds, hands, idx, forced, body, d, length, settings, rnd, deadline)
        if r and (best is None or r[0] < best[0]):
            best = r
        if best and attempt >= 2:
            break
    if not best:
        raise ValueError('No climbable line found for this body size and settings — try another seed, '
                         'a longer reach, or different pinned holds')
    cost, path, start_state = best
    return to_problem(path, holds, mode, cost, grade_idx, body, wall['height'] + wall.get('kicker', 0))


def attempt_once(srch, holds, hands, idx, forced, body, d, length, settings, rnd, deadline):
    fs = [idx[k] for k, r in forced.items() if r == 10 and k in idx]
    ff = [idx[k] for k, r in forced.items() if r == 20 and k in idx]
    ways = sorted((idx[k] for k, r in forced.items() if r in (30, 40) and k in idx), key=lambda i: holds[i].y)
    traverse = bool(settings.get('traverse'))
    feet_floor = min((h.y for h in holds if srch.foot_ok[h.i]), default=0)
    W = max(h.x for h in holds) - min(h.x for h in holds)

    def score(h):  # difficulty match, lower is better, plus variety
        return srch.diff_cost[h.i] + 1.5 * max(0, h.y - feet_floor - .3 * body.h) + rnd.uniform(0, 1)

    # start hands
    if fs:
        s1 = sorted(fs, key=lambda i: holds[i].x)
        lh, rh = s1[0], s1[-1]
    else:
        # spray walls start low: sitting or crouched, hands roughly 0.3-0.62 x height above the lowest feet
        lo, hi = feet_floor + .3 * body.h, feet_floor + .62 * body.h
        cands = [h for h in hands if lo <= h.y <= hi]
        if traverse:
            side = rnd.choice((min, max))
            edge = side(h.x for h in cands) if cands else 0
            cands = [h for h in cands if abs(h.x - edge) < .6]
        if not cands:
            return None
        a = min(rnd.sample(cands, min(4, len(cands))), key=score)
        pair = [h for h in cands if h is not a and .2 < abs(h.x - a.x) < .7 and abs(h.y - a.y) < .3]
        b = min(pair, key=score) if pair and rnd.random() < .6 else a
        lh, rh = sorted((a.i, b.i), key=lambda i: holds[i].x)

    # finish
    if ff:
        fin = ff[0]
    else:
        sx, sy = (holds[lh].x + holds[rh].x) / 2, (holds[lh].y + holds[rh].y) / 2
        if traverse:
            cands = [h for h in hands if abs(h.y - sy) < .6 and abs(h.x - sx) > .5 * W]
        else:
            top = max(h.y for h in hands)
            cands = [h for h in hands if h.y >= top - .35 and h.y > sy + .8]
        if not cands:
            return None
        want = length * .8 * max(W - .4, 0)  # longer problems drift sideways
        fin = min(cands, key=lambda h: abs(abs(h.x - sx) - want) + srch.diff_cost[h.i] + rnd.uniform(0, .6)).i

    # start feet
    if srch.campus:
        start = (lh, rh, lh, rh)
    else:
        top = min(holds[lh].y, holds[rh].y) - .4
        feet = [h for h in holds if srch.foot_ok[h.i] and h.y <= top]
        pairs = [(a.i, b.i) for a in feet for b in feet if a is not b and a.x <= b.x]
        rnd.shuffle(pairs)
        legal_pairs = []
        for a, b in pairs[:600]:
            s = (lh, rh, a, b)
            if srch.ok(s) is not None:
                # start feet as low as possible (kicker), comfortably apart
                cost = 3 * (holds[a].y + holds[b].y - 2 * feet_floor) + abs(abs(holds[a].x - holds[b].x) - .35)
                cost += 3 * abs((holds[a].x + holds[b].x) / 2 - (holds[lh].x + holds[rh].x) / 2)  # feet under the hands
                legal_pairs.append((cost + .3 * (srch.noise[a] + srch.noise[b]), s))
        if not legal_pairs:
            return None
        start = min(legal_pairs)[1]

    # waypoints, then the finish (both hands matched on it)
    path, cost, cur = [start], 0., start
    for w in ways + [fin]:
        def goal(s, w=w):
            return (s[LH] == w and s[RH] == w) if w == fin else w in (s[LH], s[RH])
        r = srch.run(cur, goal, w, deadline=deadline)
        if not r:
            return None
        c, seg, _ = r
        cost += c
        path += seg[1:]
        cur = seg[-1]
    return cost, path, start


def to_problem(path, holds, mode, cost, grade_idx, body, total):
    roles, order = {}, []
    s0 = path[0]
    for k in (LH, RH):
        roles[s0[k]] = 10
    fin = path[-1][LH]
    roles[fin] = 20
    beta, states = [], [list(s0)]
    for a, b in zip(path, path[1:]):
        for limb in (LF, RF, LH, RH):  # feet step up first, then the hand reaches
            if a[limb] == b[limb] or (mode == 8 and limb >= 2):
                continue
            j = b[limb]
            beta.append({'limb': LIMBS[limb], 'hold': holds[j].id})
            states.append(states[-1][:])
            states[-1][limb] = j
            if limb < 2 and j not in roles:
                roles[j] = 40
            if limb < 2 and j not in order and roles.get(j) == 40:
                order.append(j)
    if mode not in (4, 8):  # open feet / campus: no generated feet
        for s in path:
            for k in (LF, RF):
                roles.setdefault(s[k], 50)
    out = [{'id': holds[i].id, 'role': r} for i, r in roles.items()]
    for n, i in enumerate(order, 1):
        next(o for o in out if o['id'] == holds[i].id)['n'] = n
    start = {LIMBS[k]: holds[s0[k]].id for k in range(4) if mode != 8 or k < 2}

    def mm(x, y):  # metres, y up -> wall-image mm, y down
        return [round(x * 1000), round(total - y * 1000)]
    poses = []  # skeleton per step (start + after each move), for the stick figure
    for st in states:
        p = pose(body, [holds[st[LH]], holds[st[RH]]], [] if mode == 8 else [holds[st[LF]], holds[st[RF]]])
        poses.append(p and {'com': mm(p[0], p[1]), 'hip': mm(p[2], p[3]), 'shoulder': mm(p[4], p[5])})
    dims = {k: round(getattr(body, k) * 1000) for k in ('arm', 'leg', 'torso', 'shoulder', 'hip')}
    return {'holds': out, 'grade': grade_label(grade_idx), 'grade_index': grade_idx, 'penalty': round(cost, 2),
            'beta': {'start': start, 'moves': beta, 'poses': poses, 'body': dims}, 'engine': 'kinematic'}
