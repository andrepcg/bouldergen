# BoulderBot 2.1.1 — Climb Generation Algorithm (full reverse‑engineering report)

Source: `BoulderBot+Climbing_2.1.1_APKPure` (R8‑obfuscated, all code in package `b`, strings encrypted, heavy anti‑tamper junk).
Everything below was recovered from smali / Vineflower decompiles; obfuscated names are given in `code` so every claim can be re‑checked.
A faithful, runnable port of the four neural nets is in `_re/Nets.java` (`java Nets.java`).
Section 13 is what the developer (u/Altitude3003) has said in public, and where that matches this reconstruction.

---

## 0. TL;DR

A generated climb is the result of **two stages**:

1. **Path planner** (`hu0.qro`) – a randomised walk over a *hold graph* in millimetres (edges = 3D distance ≤ 1750 mm). It produces a "line" up (or across / around) the wall whose total length matches the **Length** slider, avoids losing height, and passes through areas that have holds of the right difficulty.
2. **Hold sequencer** (`h92.q4u`) – re‑samples that line every ~0.7–0.9 m (depending on **Difficulty** and **Hold Span**) and, around each sample point, picks a concrete hold with **weighted roulette selection**. Weights = product of ~6 hand‑written factor tables (distance, difficulty match, hold type, pull direction, structure/proximity rules) × the output of a tiny **MLP** (4 nets: start / finish / hand / foot). Then it adds feet, fills gaps, adds extra feet, scores the whole problem with a **penalty function**, retries up to 5×, keeps the lowest‑penalty climb.

The *grade* shown for a generated climb is **not estimated from the result**; it is just the Difficulty slider mapped to a Font/V grade (plus a wall‑angle offset).

Pro hold attributes and where they actually matter (user‑created photo walls):

| Pro attribute | Used? | Where |
|---|---|---|
| Fine difficulty (12 levels) | yes | everywhere (normalised difficulty, planner node filter, density check, foot flag) |
| Hold type (Jug/Edge/…) | yes | ×10 / ×1e‑4 selection factor when the user selects hold types, penalty, gap‑fill reach factor |
| Direction (8 arrows) | yes | pull‑direction compatibility factor, foot rules, gap‑fill reach factor |
| Size | **no** (for photo walls) | only feeds `tlk.y6y` “grip”, which is consumed only by the *other* engine used for walls that ship with a server 3D model (§10) |

---

## 1. Entry point & engine selection

`z2a.gj1(pte wall, w1l settings, rt9 cancel)`:

```
if count(non-foot holds) < 2: error
if not wall.model().hasServerModel:          # nz7.iyx == false  -> photo / user-created wall
    return h92.q4u(wall, settings, cancel)   # <-- the algorithm documented here
else:                                        # wall has a downloaded "P$" binary model (3D scan, precomputed difficulty)
    paths = hu0.qro(model) ; q5z(model, …).q4u(path, …)   # body-position simulator engine (§10)
```

`nz7.iyx` is `true` only when `uue` could load the per‑wall binary package from disk (`eg3.kmg(wallId)`, file magic `50 24` = "P$"). User‑created photo walls never have it.

---

## 2. Data model

### 2.1 Hold (`gkh`)

| field | meaning |
|---|---|
| `wj9` | id |
| `rj`, `hot` | x, y in image pixels (0…16384), y grows downward |
| `kmg` | difficulty code (see 2.2) |
| `l20` | direction bitmask (see 2.4) |
| `q4u` | type bitmask (see 2.3) |
| `olk` | size (int, 0 = default = 1000) |
| `liq` | **isFoot** = `192 ≤ kmg ≤ 208` |

New hold defaults (`rco`): difficulty 64 (Medium), type 2 (Edge), direction 1 (↓).

### 2.2 Difficulty codes

Free picker: **Easy 32, Medium 64, Hard 96, Foot 200**.
Pro fine‑tune (tap upper/lower half of hold to step, `ust` case 6): `24, 32, 40, 56, 64, 72, 88, 96, 104, 192, 200, 208`
Groups: Easy−/Easy/Easy+ = 24/32/40, Medium−/Medium/Medium+ = 56/64/72, Hard−/Hard/Hard+ = 88/96/104, Foot−/Foot/Foot+ = 192/200/208.

Three different numeric scales are derived from the code:

| code | **gen** `hd` (h92, 0..1) | **planner** `s4_.ujk`/255 (`tlk.l2z`) | `s4_.yn`/255 (`tlk.a4e`) |
|---|---|---|---|
| 24 | 0.000 | 0.05 | 0.10 |
| 32 | 0.125 | 0.10 | 0.125 |
| 40 | 0.250 | 0.15 | 0.15 |
| 56 | 0.375 | 0.20 | 0.20 |
| 64 | 0.500 | 0.30 | 0.25 |
| 72 | **0.675** (sic) | 0.40 | 0.30 |
| 88 | 0.750 | **0.50** (falls through to default) | 0.35 |
| 96 | 0.875 | 0.60 | 0.40 |
| 104 | 1.000 | 0.70 | 0.45 |
| 192 | 0.125 | 0.80 | **0.50** (falls through) |
| 200 | 0.500 | 0.85 | 0.70 |
| 208 | 0.875 | 0.90 | 0.90 |
| other | 0.5 | 0.5 | 0.5 |

All `/255` values are `round(v*255)` clamped to 0..255. `tlk.qc` (“is foot/very hard, excluded from planner start/top logic”) = `l2z/255 ≥ 0.8` → exactly the three foot codes.

### 2.3 Hold types (`qii`) and settings type flags

| type | value | settings flag bit |
|---|---|---|
| Jug | 1 | 0x020000 (131072) |
| Edge | 2 | 0x040000 |
| Crimp | 4 | 0x080000 |
| Sloper | 8 | 0x100000 |
| Pinch | 16 | 0x200000 |
| Pocket | 32 | 0x400000 |
| Crack | 64 | 0x800000 |
| none | 0 | – |

`typeSum = Σ type values whose flag bit is set` (`h92.rj` map).

### 2.4 Direction (`l20`, pull direction arrows)

| value | arrow | angle `c24.hot` (tlk) |
|---|---|---|
| 1 | ↓ (default) | 0 |
| 2 | ↙ | 45 |
| 4 | ← | 90 |
| 8 | ↖ | 135 |
| 16 | ↑ (undercling) | 180 |
| 32 | ↗ | 225 |
| 64 | → | 270 |
| 128 | ↘ | 315 |
| 0 | any | – |

Direction groups used by the scorer: `UP = 56 (↖↑↗)`, `LEFT = 14 (↙←↖)`, `DOWN = 131 (↘↓↙)`, `RIGHT = 224 (↗→↘)`.

### 2.5 Size

`olk`, 0 → 1000. Upper‑half tap `size = round(size/0.9)`, lower‑half `round(size*0.9)` (`ust` case 0). Only used in the grip formula (§9.4).

### 2.6 Roles in a generated climb

`10` start, `20` finish, `30` zone/“key” hand hold (forced or circuit checkpoints), `40` intermediate hand, `50` foot.

---

## 3. Generation settings (`w1l`) and UI mapping

`w1l(difficulty, length, lengthVariation, holdSpan, flags, forcedHolds, linePoints)` built in `drf.r5u()`:

| field | pref key | default | range | UI labels |
|---|---|---|---|---|
| `wj9` difficulty `d` | `parameterDifficulty` | 0.25 | 0..1 | <.1 Very Easy, <.25 Easy, <.4 Moderate, <.6 Medium, <.75 Hard, <.9 Very Hard, else Extreme |
| `rj` length `L` | `parameterLength` | 0.5 | 0..1 | <.2 Very Short, <.4 Short, <.6 Medium, <.8 Long, else Very Long ("From Line" if a line is drawn) |
| `hot` length variation `V` | `parameterLengthVariation` | 0.0 | clamp 0..0.5 | (no UI control found – hidden pref) |
| `kmg` hold span `S` | `parameterHoldSpan` | 0.5 | 0..1 | <.2 Very Short, <.4 Short, <.6 Normal, <.8 Long, else Very Long |
| `l20` flags | `parameterTags` | 0 | bitmask | see 3.1 |
| `q4u` forced holds | – | {} | Map holdId → role (10/20/30/40/50) | |
| `olk` line points | – | [] | list of (x_px, y_px) the user drew | |

**Adjustable‑angle walls** (`y8e`, degrees: 90 vertical … 180 roof, 130 = 40° overhang default): if a non‑default angle `a` is selected,
`d ← clamp(d − 0.2·(a − 130)/40, 0, 1)` (steeper → easier holds), while the *displayed* grade is shifted by `r72` steps for `(a − baseAngle)`:
`−90:−10, −85:−9.55, −80:−9, −75:−8.55, −70:−8, −65:−7.55, −60:−7, −55:−6.55, −50:−6, −45:−5.55, −40:−5, −35:−4.55, −30:−4.38, −25:−3.92, −20:−3.35, −15:−3, −10:−2.07, −5:−1.14, 0:0, 5:.61, 10:1.53, 15:2.3, 20:3.27, 25:4, 30:5, 35:5.5, 40:6, 45:6.5, 50:7, 55:7.5, 60:8, 65:8.5, 70:9, 75:9.5, 80:10, 85:10.5, 90:11` (grade‑index steps, rounded).

### 3.1 Flags (`w1l.l20`)

| bit | name | used by generator? |
|---|---|---|
| 0 (none of 2/4/8) | Follow Hands – feet on all highlighted holds | yes (feet mode) |
| 2 | Set Feet – only foot holds for feet | yes |
| 4 | Open Feet – any wall hold for feet | yes (no generated feet) |
| 8 | No Feet (campus) | yes (no generated feet) |
| 16384 | Circuit | yes |
| 32768 | Traverse | yes (planner length target) |
| 0x20000…0x800000 | hold‑type filter (Jug…Crack) | yes |
| 32 Custom Rules, 64 No Matching, 128 No Hooks, 256 Free Kicker, 512 Sit Start, 1024/2048/4096 Chip Set 1/2/3 | rule labels | **no** (only displayed) |
| 33554432 Technical, 67108864 Powerful, 134217728 Endurance, 268435456 Dynamic, 536870912 Static, 1073741824 Replica, 2147483648 Balance, 4294967296 Precision, 8589934592 Coordination, 17179869184 Compression, 34359738368 Small Box, 68719476736 Reachy | style tags | **no** (only labels / filters) |

`feetMode = 2 | 4 | 8 | 0` (first of Set/Open/No set).

### 3.2 Grade mapping

`gradeCode = whh.iyx(d)` = `grades[round(clamp(d,0,1)·23)]` over the 24 Font codes below, then clamped to the wall's range (default **[96 (4), 196 (8A+)]**; server walls may define their own).

| code | Font | V | `xtj` target hold difficulty (planner scale) |
|---|---|---|---|
| 72 | 3 | VB | 0.00 (tol .3) |
| 96 | 4 | V0 | 0.05 (.25) |
| 120 | 5A | V1 | 0.10 |
| 128 | 5B | – | 0.12 |
| 136 | 5C | V2 | 0.15 |
| 144 | 6A | V3 | 0.20 |
| 148 | 6A+ | – | 0.25 |
| 152 | 6B | V4 | 0.30 |
| 156 | 6B+ | – | 0.33 |
| 160 | 6C | V5 | 0.36 |
| 164 | 6C+ | – | 0.40 |
| 168 | 7A | V6 | 0.45 |
| 172 | 7A+ | V7 | 0.50 |
| 176 | 7B | V8 | 0.55 |
| 180 | 7B+ | – | 0.63 |
| 184 | 7C | V9 | 0.66 |
| 188 | 7C+ | V10 | 0.70 |
| 192 | 8A | V11 | 0.72 |
| 196 | 8A+ | V12 | 0.74 |
| 200 | 8B | V13 | 0.76 |
| 204 | 8B+ | V14 | 0.78 |
| 208 | 8C | V15 | 0.80 |
| 212 | 8C+ | V16 | 0.82 |
| 216 | 9A | V17 | 0.84 |

(V list maps the nearest lower code; tolerance column is 0.2 except where noted and is **never read**.)
`targetDiff = xtj[gradeCode].target` (fallback `d`) – used by the planner only.

---

## 4. Stage 0 – wall graph (`uue`, photo walls)

```
H_mm   = wall.heightMm                      # user-entered wall height
angle  = wall.angle (deg, 90..180; 0 -> 130)
minY,maxY = min/max hold y_px (clamped 0..16384);  minX = min hold x_px
scale  = max((maxY-minY)/H_mm, 0.001)       # px per mm
θ      = (angle-90)°
for each hold g:
    x  = round((g.x_px - minX)/scale)       # mm along wall, horizontal
    h  = round((maxY - g.y_px)/scale)       # mm along wall surface, upward
    node = tlk(g, x=x, y=round(cos θ·h) /*vertical height*/, z=round(sin θ·h) /*overhang depth*/,
               wallAngle=angle, l2z=ujk(code), a4e=yn(code), grip=grip(type,size,code), qc=l2z/255≥0.8)
edges: for every pair with |dx|,|dy|,|dz| ≤ 1750 and 3D dist ≤ 1750: cost = round(dist)   (mm)
```

Because the holds lie on a plane, the edge costs equal in‑plane distances; the wall angle only changes *vertical height* (`y`) used by the planner's “don't go down” and start/top logic.

---

## 5. Stage 1 – path planner (`hu0.qro` + walk `hu0.q4u`)

### 5.1 Node filter `uia`

```
nodes = { n : not n.isFoot and |n.l2z/255 − targetDiff| < 0.5 }  ∪  forced non-foot holds (role ≠ 50)
```

### 5.2 Length target `hke.olk` → `qav(centre, [min,max])`

```
W   = maxX − minX              (over non-qc nodes)
D   = round(sqrt((maxY−minY)² + (maxZ−minZ)²))     # wall diagonal height incl. overhang
base= D>2000 ? D−1000 : D−800
if circuit:   v = 2W + 2·base;  range=[min(4000,v), v]; centre = mid(range)
elif traverse:base'=min(2000,base); range=[min(1000,W), round(sqrt(W²+base'²))]; centre=W
else:         f = first i where D < [3000,5000,8000,10000,12000][i] and W < [3000,3000,4000,5000,8000][i]
                  → [1.25,1.2,1.15,1.1,1.05][i], else 1.0
              centre = base; range = [1000, max(round(W·f)+base, 1000)]
qav(t) = t≤.5 ? lerp(min, centre, 2t) : lerp(centre, max, 2t−1)
```

### 5.3 Start candidates

```
if linePoints:                                   # "From Line"
    snapped = for p in linePoints: nearest non-foot hold with |Δx_px|<700 and |Δy_px|<700
    snapped = distinct(snapped)                  # keep order
    starts = [snapped.first]; nodes = snapped; end = snapped.last
elif forced role-10 holds:
    starts = those; nodes = uia()
else:  # lowest region
    cells = group all nodes by (x/250, z/250); cell.low = min height
    starts = nodes of globally lowest cell
    for each x-column c: if column low within 1000 mm of global low and is the local low
         (within 150 mm of the lowest in columns c±2): add cells of that column whose low is within 75 mm
    # expand to "first hand holds": for each start, neighbours not qc with edge cost in
    #   [700,1350] (≥3 found) else [600,1600] (≥3) else [500,2000]
    if |expanded| > 3: starts = expanded
    else: starts = non-qc nodes with height ≤ minHeight + 500
    nodes = uia() minus nodes that are below the start band:
        n ∉ starts, n.h < max start h, and (n.h ≤ min start h or n.h < min h of its ≤3 cheapest start neighbours)
end = linePoints ? last : (forced role-20 ? random forced finish : null)
mustVisit = forced holds with role ∉ {10,20}  (or null)
top = (end==null) ? highest region (same cell trick, max height) : null
```

### 5.4 Other planner parameters

```
mults = forced non-start holds ? [1,2,4,8,8,16,16,64,64,128,256]
      : circuit ? [1,2,4,4,4,8,8,8,16,16,16,32,32,32] : [1,2,4,8,16]
steep = mean(node.wallAngle − 90)                       # degrees past vertical
dropTol(mm) = steep≤10:80, ≤20:70, ≤30:60, ≤40:50, ≤50:40, ≤60:30, ≤70:20, ≤80:15, else 10
LV = L − V
if LV ≥ 0.7 and |starts| ≥ 5 and xSpan(starts) ≥ 900:          # long climbs start at a wall edge
    f = xSpan ≤3000:.66, ≤4000:.6, ≤5000:.5, ≤8000:.3 ; m=(xSpan − round(xSpan·f))/2
    starts = starts with x ≤ minX+m or x ≥ maxX−m
```

### 5.5 Random walk `q4u(starts, nodes, target, end, mustVisit, circuit, LV)`

```
avail = copy(nodes); prio = mustVisit-by-id
cur = random(starts); remove cur from avail/prio; path=[cur]; cost=0
filters = [ e: 500≤c≤1000 or (c≤1000 and e∈prio),  e: c≤1000,  e: c≤1200 ]
firstFilter = (!circuit and LV≥0.8 and xRange(nodes)≤4000) ? (e: |Δx|/c ≥ 0.3) : null   # only first move
loop:
    cand = edges(cur) to nodes in avail not already in path   (circuit: may return to start)
    if cand empty or all costs ≥1200: return null
    if cost ≥ target: return (cost, path)
    if end ∈ path: return (cost, path)
    if circuit and |path|==4: re-add start (and nodes adjacent to it) to avail
    C = first filter result (∧ firstFilter) that is non-empty; if none: return null
    if end ∈ C: append end; return
    if any prio node ∈ C: nxt = prio node with smallest cost to cur
    elif circuit and |path|≥4 and start∈C and cost ≥ 0.75·target: close loop; return
    else nxt = uniform random from C
    # spread the route: drop neighbours of cur that are not much farther than the chosen step
    for each neighbour e of cur (except end, except prio):
        if nxt has no edge to e or cost(cur,e) ≤ (circuit?300:500) + cost(cur,nxt): avail.remove(e)
    path += nxt; cost += cost(cur,nxt); cur = nxt
```

### 5.6 Path search & scoring

```
for k in mults (stop at first k that yields results):
    lo = max(range.min, qav(max(L−V,0)) − 500k);  hi = max(qav(min(L+V,1)) + 500k, lo)
    walks = circuit ? 500 : 100
    for round in 1..3:
        if |results| ≥ 2 and elapsed ≥ 5 s: break
        cands=[]
        repeat walks times:
            target = end ? 100000 : randInt(lo, hi)
            p = walk(...); reject null/empty, reject if end set and not reached,
            reject if circuit and p.first ≠ p.last
            s = 0
            if !circuit: s += 3·Σ max(0, (h[i−1] − h[i]) − dropTol)
            if end==null and cost∉[lo,hi]: s += 2·distance outside
            if top and end==null and p.last ∉ top:
                (gap,c) = nearest top node by edge cost → (max(top.h−last.h,0), c)
                          else (max(mean(top.h) − last.h, 0), 2000)
                s += 8·c + 3·gap
            for (w,need,tol,R) in [(5,3,.175,400), (3,5,.325,500)]:          # difficulty density
                samples = walk p every round(0.6R) mm; at each sample take the nearest node
                          among those adjacent to both segment ends (or the ends); + p.last
                for q in distinct(samples):
                    n = [|q.l2z/255 − targetDiff| ≤ tol] + #{neighbours ≤ R with |l2z/255−targetDiff| ≤ tol}
                    s += 100·w·max(0, need − n)
            if s ≤ 1e−4: results += p; break
            cands += (p,s); if |cands| ≥ 25 or round time ≥ 200 ms: break
        results += random(5 lowest-score cands)
return results      # h92 uses only results[0]
```

---

## 6. Stage 2 – hold sequencer `h92.q4u(wall, s, cancel)`

### 6.1 Normalisation (metres)

```
scale = (maxY_px − minY_px) / (wall.heightMm/1000)       # px per metre
for each hold g:  P = l3c(g,
      x  = (g.x_px − minX_px)/scale,
      y  = (maxY_px − g.y_px)/scale,       # height above lowest hold
      dt = (g.y_px − minY_px)/scale,       # distance below top hold ("108")
      hd = genDifficulty(g.code),          # table 2.2
      role = null)
```

### 6.2 Forced holds

```
F = s.forced
if circuit: drop role-20 entries
for role in {10,20}: if > 2 holds forced with that role:
     shuffle; with p=.5 keep 1, else keep first + first other within (1.75 − 0.5·d) m
```

### 6.3 Path → sample points

```
path = hu0.qro(model with s)[0]  → map tlk to P (x,y)
a = 2.125 − 0.75·(d + S)
step() = 1 / U(a − .25, a + .25)          # metres between samples; e.g. d=S=.5 → 0.69…0.89 m
pts = [path[0]]; last = segStart = path[0]; i = 1; st = step()
while i < |path|:
    d1 = |last − segStart|, d2 = |last − path[i]|
    if d1 ≤ st ≤ d2: t=(st−d1)/(d2−d1); q = segStart + t·(path[i]−segStart)
                     pts += q; last = segStart = q; st = step()
    else: segStart = path[i]; i++
if |pts|<2 or |last − path.end| > 1/(a+.25): pts += path.end
```

### 6.4 Attempt loop (≤ 5 attempts, keep lowest penalty, stop at penalty 0)

```
for attempt in 1..5 while !cancelled:
  je = state(avail = all P minus forced holds, chosen = [], circuit)

  # starts
  if F has role 10: add them (role 10) else  start = pick(je, 10, NetA, pts.first)
  # finish
  if !circuit: if F has 20: add, else pick(je, 20, NetB, pts.last)
  # second start
  if no forced start and (rand < .5 or start.hd − d > .25): pick(je, 10, NetA, pts.first)
  else if 2nd forced start exists: add it

  # start feet  (only feetMode ∉ {4,8})
  if feetMode ∉ {4,8}: startFeet()                        # §6.5

  # extra finish
  if !circuit and rand < .25 and no forced finish: pick(je, 20, NetB, pts.last)

  # forced zones / intermediates
  for (id,role∈{30,40}) in F: add hold with role; remove the middle sample point nearest to it if < 0.5 m

  # middle hands
  for k, p in enumerate(middle sample points):
      if k == 0 and two starts exist:
          skip if p.x strictly between the starts' x and some start.y + .1 > p.y
          skip if some start has |start.x − p.x| < .3 and start.y + .1 > p.y
      pick(je, 40, NetC, p)

  # circuit checkpoints
  if circuit and no role-30 hold:
      n40 = #role-40 holds; K = n40>30 ? 4 : n40>20 ? 3 : 2
      stepK = n40/(K+1); targets = {round(i·stepK) : i=1..K}
      w = n40/(K+1) <1:0, <3:1, <5:2, <7:3, else 4
      for t in targets: among role-40 indices t−w..t+w choose the one farthest (max of min distance)
                        from starts/finishes/already-chosen checkpoints → becomes role 30

  # gap filling
  for each non-foot hold a: b = nearest other non-foot (skip start→non-start pairs); each pair once
      thr = dirF(a)·dirF(b)·K·(0.5S + 0.75)·typeF(a)·typeF(b)
            K = d≤.1:1.1, ≤.2:1.3, ≤.5:1.5, else 1.8
            dirF (pke.liq): ↖/↗ .975, ←/→ .95, ↙/↘/↓ .925, ↑ or any 1.0
            typeF: Jug 1.05, Sloper 1.025, Edge/Pocket/Crack .975, Crimp .95, else 1
      if |a−b| > thr: pick(je, 40, NetC, midpoint(a,b))

  # extra feet (feetMode ∉ {4,8})
  for each hold h with role ∉ {10,50}:
      (dx,dy) by h.dir: 4 or 2 → (.5,0); 64 or 128 → (−.5,0); 8 → (.3,.3); 32 → (−.3,.3); 16 → (0,.3); else (0,0)
      t = (h.x + dx + U(0,.6) − .3,  h.y + dy − (1.33 − .25d))
      r = (isFoot ? .4d + .2 : .3d + .4)·(S + .5)
      if no hold within r of t (Set Feet: only foot holds count): pickSpaced(je, 50, NetD, t)

  penalty = score(je)                                     # §6.6
  keep (je, penalty); if penalty == 0: break
return best (lowest penalty); none → error ecb
```

### 6.5 Start feet (custom scorer, not `pick`)

```
S2 = first 2 role-10 holds; meanY, meanX of S2; Δ = |y1 − y2|
spread = Δ>1 ? 1.0 : Δ>.5 ? 1.2 : Δ>.25 ? 1.25 : 1.5
baseY = meanY − spread
(offX,offY) = all start dirs == 14 ? (.5,0) : all == 224 ? (−.5,0) : all == 56 ? (0,.3) : (0,0)   # see quirks
targets = [(meanX+offX − U(.25,.75), baseY+offY), (meanX+offX + U(.25,.75), baseY+offY)]
(p1,p2) by d: ≤.1 (1,1), ≤.2 (1,.5), ≤.3 (.8,.3), ≤.4 (.6,.1), ≤.5 (.5,0), ≤.6 (.4,0), ≤.7 (.2,0), ≤.8 (.1,0), ≤.9 (.05,0), else (0,0)
slope = |Δy|/|Δx| of the first two sample points (0 if y equal, 10 if x equal)
   slope>4: p1=0, p2/=4 ; slope>2: p1/=4, p2/=2 ; slope>1: p1/=2
if offY < .1: with prob p1 add target (meanX+offX+U(−.75,.75), baseY + U(.5,.75)·spread)
              with prob p2 add target (meanX+offX+U(−.75,.75), baseY + U(.2,.6)·spread)
pool = avail minus holds within spacing radius of chosen holds (radius: d≤.1 .4, ≤.3 .5, ≤.5 .6, else .75; box test)
for i, t in enumerate(targets):
    C = holds of pool within first radius r∈[.2,.3,.4,.5,.6,.75] giving ≥2 (excluding already chosen)
    for c in C (dist δ):
       f1 = δ<.1:2, <.2:1.5, <.3:1.2, <.4:1, <.5:.75, else .5
       Δ = d − c.hd
       f2 (c is foot hold): d>.75 & hd<.4 → .01; Δ<−.5 → .2; Δ<−.25 → .3; Δ>.5 → .5; Δ>.25 → .75; else 1
       f2 (hand hold):      d>.4 & hd<.4 → .01; Δ<−.5 → .05; Δ<−.25 → .1; Δ<−.1 → .2; Δ>.5 → .1; Δ>.25 → .2; Δ>.1 → .3; else .5
       f3 = foot & dir==16 → .05; foot & ((dir==8 & i==0) or (dir==32 & i==1)) → .01; else 1
       m  = min distance to already chosen feet (100 if none)
       f4 = i==0 → 1
            i==1 → m<.2 .01, <.4 .1, <.6 .2, ≤.9 1, ≤1.0 .5, ≤1.2 .2, ≤1.5 .05, else .01
            i≥2  → m<.3 .2, <.5 .5, else 1
       n  = #other C members lower than c.y − .1 with |x − c.x| ≤ .15
       f5 = n==0 1; i>1 2; n==1: d<.5 .1, d<.75 .5, else .9; n≤3: d<.5 .02, d<.75 .1, else .2; else .01
       f6 = c.y > meanY → 1e−6; c.y > meanY − .2 → .01; else 1
       w  = f1·f2·f3·f4·f5·f6
    if C non-empty: add roulette(w) as role 50
    elif i ≤ 2:     pick(je, 50, NetD, t)
```

### 6.6 Penalty `score(je)` (lower is better)

```
T = 0.5S + 0.5d + 0.75
for each chosen hold h with neighbours N (all other chosen holds sorted by distance):
  if role 10 and !circuit and ∃ o∈N role∈{40,20,30} dist<.4                          : +5
  if role 10 and ∃ o∈N role∈{40,20,30}, dist<1, h.y−o.y > −.1, 3|Δy|>|Δx|          : +3   (hand hold under a start)
  if role∈{10,20} has a same-role partner s and ∃ other o within .75 with
        1.5·dist(h,s) > dist(h,o)+dist(s,o)                                          : +10  (hold between paired starts/finishes)
  if role 20 and !circuit and ∃ o role∈{40,10,30}, dist<1, h.y−o.y < .1, 3|Δy|>|Δx| : +40  (hand hold above the finish)
  if role 40 and none of 6 nearest non-feet has dist < 1.25T and h.y−o.y < .1      : +20  (dead end)
  if the 2 nearest non-feet are both < .3                                            : +5
  Δd = h.hd − d: >.79 +100, >.59 +25, >.49 +5, <−.79 +20, <−.59 +2, <−.49 +1
  k = (role∈{10,20} and no same-role partner) ? 1 : 2
  if any of k nearest non-feet farther than T                                        : +20
  if typeSum≠0 and role≠50 and h.type ≠ typeSum   (exact compare!)                   : +(start/finish?5:1)·(h.type==0?1:2)
```

---

## 7. The candidate scorer `pick(je, role, net, point, spaced)` (`h92.wj9`)

```
cands = role==50 ? avail : avail minus foot holds
spacedSet = spaced ? cands minus holds within spacing radius (6.5) of chosen : cands
typeSum = Σ selected types ; setFeet = flags&2
startFeetPhase = role==50 and no chosen hold has role ∈ {40,30,20}

radii = role==50 ? (setFeet ? [.4,.5,1,1.25,2.5,100] : [.5,1,1.25,2.5,100])
      : [r0] + [x∈{.5,.75,1.25,2.5,100} : x>r0],  r0 = circuit ? .25 : (role==10 and chosen≠∅) ? 1.25 : .25d+.375
C = within(point, first radius with ≥3 cands) else all cands at distance 0
reach = 0.5S + 0.5d + 0.75

for c in C (distance δ):
   W = f9 · f81 · f19 · NN · f13 · f67
take top 8 by W, roulette-select; if !setFeet and choice ∉ spacedSet → return null; else add with role
```

**f9 – distance to target:** δ<.25 → 4, <.375 → 3, <.5 → 2, <.75 → 1, <1 → .75, else .2

**NN** = first output of `net(features(c))` (§8).

**f81 – structure/proximity** (N = chosen holds within 1.5 m of c, with distance), first rule that fires:

| # | condition | value |
|---|---|---|
| 1 | finish within .5 and below c | 1e−9 |
| 2 | finish within .5 | 1e−6 |
| 3 | startFeetPhase and a start with start.y − c.y < .5 | 1e−6 |
| 4 | startFeetPhase and exactly 1 foot chosen and a foot within .5 | 1e−6 |
| 5 | (role 10, nothing chosen, c.y < .75) or (role 40 and c.y < 1.0) | 1e−5 |
| 6 | startFeetPhase and a start within .75 | 1e−4 |
| 7 | a finish within 1.0 that is below c | 1e−4 |
| 8a | role 50, startFeetPhase, <2 feet, d<.6, c.y<.8, and some hold h with h.y<c.y, c.y−h.y<.5, \|Δx\|<Δy | 1e−4 |
| 8 | ≥3 chosen holds within .5 | 1e−4 |
| 9 | role 40 and every N is a finish farther than `reach` (incl. N empty) | .01 |
| 10 | role 50 and a foot within .5 | .05 |
| 11 | role ≠ 50 and a start within .75 with c.y ≤ start.y | .05 |
| 12 | role 40 and all N are feet | .1 |
| 13 | anything within .25 | .3 |
| 14 | otherwise | 1.0 |

**f19 – difficulty match**, Δ = d − c.hd:

hands (role ≠ 50): Δ<−.5 → .001; [−.5,−.375) → .01; [−.375,−.25) → .1; [−.25,−.125) → .3; [−.125,.124) → **1.0**; [.124,.24) → .5; [.24,.374) → .2; [.374,.49) → .05; ≥.49 → .01

feet (role 50): c.hd ≤ .5 → .2; Δ<−.5 → .1; Δ>−.49 → .5; else 1.0

**f13 – hold type:** role 50 or typeSum==0 → 1; `c.type & typeSum ≠ 0` → **10**; else **1e−4**.

**f67 – pull direction** (U/L/D/R = c.dir ∩ 56/14/131/224; primed = same for neighbour):
```
if c.dir == 0: 1
elif role ∈ {20,50}: U → .75 ; D → 1.25 ; else 1
else n = nearest N that is not foot/finish; if none: 1
     dx = n.x − c.x; above = n.y − c.y > .1
     role 10, n is start, (R∧R′ or L∧L′)  → .01   (both starts pull the same way)
     R′∧R ∧ dx < −.25                    → .2
     L′∧L ∧ dx >  .25                    → .2
     U ∧ |dx| > .75                       → .1
     above ∧ U                            → .01
     above ∧ (L or R)                     → .75
     U′ ∧ (L or R)                        → .5
     D′ ∧ D                               → 1.25
     U′ ∧ U                               → .75
     else                                 → 1
```

`roulette` (`s4_.w86`): sum weights, draw `U(0,sum)`, walk entries sorted by weight descending; all‑negative weights → uniform.

---

## 8. Neural networks (`lus`, evaluator `sb5.ujk`)

### 8.1 Evaluator

```
x_i = act_in[i](feature_i)  (missing feature → 0);  x.append(1)          # bias
for layer l:
    x[last] = 1
    y[o] = Σ_i x[i]·W[l][o][i]          o over next layer width (incl. its bias slot) or #outputs for last layer
    y[o] = act[l+1][o](y[o])
    x = y
return x[0]
acts: 100 tanh, 111 step(>0), 320 relu, 600 sigmoid, 810 identity, 811 softplus
```

### 8.2 Features (`h92.kmg`)

| id | meaning |
|---|---|
| 558 | settings difficulty d |
| 1000492 | d − hold hd |
| 557 | y (m above lowest hold) |
| 108 | depth below top hold (m) |
| −33 | x (m) |
| 1000493 | isFoot (0/1) |
| −34, 1 | x − n1.x, y − n1.y (n1 = nearest chosen non‑foot hold) |
| 2200, 20 | x − n3.x, y − n3.y (**n3 = 3rd nearest**, `getOrNull(2)`, fallback n1) |
| 109 | angle (rad·0.0174533 of degrees) = `90° − atan2(y − x, midY − midX)` with mid = mean(n1,n3), wrapped to (−180,180] — note the `y − x` bug |

Features −34…109 only exist if a non‑foot hold has already been chosen (otherwise 0).

### 8.3 Networks

| net | used for | inputs | layers (acts) |
|---|---|---|---|
| A `l20` | start (role 10) | [557] | in(810) → 3(111,810,·) → 3(111,111,·) → 1 sigmoid |
| B `if3` | finish (role 20) | [557,108,1000493] | in(320,320,100) → 4(810,600,100,·) → 4(111,100,320,·) → 1 sigmoid |
| C `qc` | hand (role 40) | 11 features | in(100,100,811,320,320,100,320,100,811,600,320) → 11(111,600,810,320,600,600,600,320,600,111,·) → 1 step |
| D `yn` | foot fallback (role 50) | first 10 features (no 109) | in(100,600,320,100,600,811,600,810,320,600) → 3(811,811,·) → 1 sigmoid |

Measured behaviour (`_re/Nets.java`):

* **Net A (start)**: y<0.38 → 1.0; 0.38–1.0 → 0.5; 1.0–1.24 → 1.0; 1.24–1.48 → 0.5; >1.48 → 0.099.
* **Net B (finish)**: hand hold: depth‑below‑top < ~0.17 m → 1.0, < 0.50 → 0.5, else ≈0; foot hold: <0.14 → 0.5, else 0 (y irrelevant).
* **Net C (hand)**: output is effectively binary (step); ~60 % of random inputs pass. Strongest positive dependence on feature 109 (corr .57) and height (.41); negative on `d−hd` (−.13) and dx3 (−.11).
* **Net D (foot)**: ~93 % pass; lower for deeper (lower) holds (−.26) and when the foot is far above the nearest hand (dy1 −.22).

### 8.4 Weights (verbatim, `W[layer][out][in]`, last input = bias)

```
NetA W = {{{-10,10},{7.296841850760454,-10},{0,0}},
          {{-10,-1.5854522686571235,-1.5048857636634352},{1.5337423897395468,3.953566595898582,-3.2471751548709413},{0,0,0}},
          {{10,-2.207778986783807,0},{0,0,0}}}
NetA act = {{810,810},{111,810,810},{111,111,810},{600}}

NetB W = {{{0.3483273715045546,-10,-4.692557621897737,2.23190094269267},{0,-4.731169604714214,2.945578232621898,6.098418280140571},{-10,-6.320810288220004,0,-7.688058198456243},{0,0,0,0}},
          {{5.437875042634489,-10,0,5.528494215877817},{-10,0,-3.0408353528769645,10},{-9.219721548948856,-2.018733707374574,10,-10},{0,0,0,0}},
          {{7.848287820974292,-10,-10,10},{0,0,0,0}}}
NetB act = {{320,320,100,810},{810,600,100,810},{111,100,320,810},{600}}

NetC W = {{{-0.37146900130988364,-7.080198506947194,10,-6.361165078296614,-6.117606523511805,8.53856768872124,7.755924594288464,10,8.428974079698087,-4.877199971928732,8.299436152637277,0},
           {-4.396682348477716,-8.683907880872967,0,-6.959702725972868,0,-4.829647421871775,-7.98359646386128,-2.5763313865692634,-8.884387412110469,0,-6.4106049453761464,0},
           {-5.232763858785727,4.806706367081677,-7.266032811868557,-10,-1.1221857880206194,8.872116520893986,0.07716306822010743,3.188828119871921,6.405517504921057,0,-10,6.001591206746118},
           {0,-9.54252527773629,-2.5058904244251456,0,1.6168513407463134,7.180858714114219,6.253741088610005,0,10,0.8711493228770681,-1.996086252739011,3.9316403713504093},
           {-5.746476806098379,4.175797539248688,-7.506789492658905,0,-6.869071450862395,0.37257466747008017,-8.949984289534703,-10,8.107506815535151,-1.501554870999974,-10,10},
           {-7.255123808354263,-8.6848206808998,0,0,0,0,2.4324199967694002,0.3445078215855588,7.594367632376187,3.4762703966984922,0,-6.764759882544194},
           {9.372772465955444,4.494374516771991,-4.3135489903716095,0,0.9201059141313034,1.4919524066493235,-1.9891831115092184,-7.611622730479688,0.7037942662336449,-6.541413084063552,-10,7.601707106035432},
           {3.9976897915481575,-10,-8.826549285752902,-0.0039817063272415965,-8.040108985594323,0,2.710645394844944,-10,-0.15821012108391264,-4.64912046920543,-2.797714214700187,-2.2918733870276857},
           {-7.188245337977063,-3.9632900759032648,-5.780252501333423,2.800450848261683,4.849325326321063,-5.9816437856470674,-9.955073539316782,0,-0.2364659859029743,-1.9355094133683846,-9.414950149930217,0.865237235873618},
           {-3.6185741156566866,2.435059312789559,-6.291189383867262,-3.3489014759015814,-9.764754815747018,7.493011271582276,3.80582730786179,-6.1242350796480505,-1.9653851619811522,0,4.95499837579375,-1.41975312267164},
           {0,0,0,0,0,0,0,0,0,0,0,0}},
          {{0,10,-0.6602611034815752,0,0.4199799388493548,1.1879131487989874,-5.7282559119542125,-7.637834330186478,-4.593949683027214,3.0279716181465854,-7.554661058317458},
           {0,0,0,0,0,0,0,0,0,0,0}}}
NetC act = {{100,100,811,320,320,100,320,100,811,600,320,810},{111,600,810,320,600,600,600,320,600,111,810},{111}}

NetD W = {{{4.996103394679435,-10,10,-10,-2.9523394237592395,-1.4641649220139066,2.5165080379227787,-6.536813977098224,2.3942030089294217,-3.9583240458784434,4.303306782041423},
           {-0.3069117579433993,0,-10,-6.954837509330643,0.9202763677350744,10,-5.344331071087192,1.750173792869446,0,1.5004835183053533,1.737142244237142},
           {0,0,0,0,0,0,0,0,0,0,0}},
          {{10,6.988867073341299,-8.650445660655961},{0,0,0}}}
NetD act = {{100,600,320,100,600,811,600,810,320,600,810},{811,811,810},{600}}
```

(Weights clipped at ±10 and exact zeros suggest they were evolved/pruned, not gradient‑trained.)

---

## 9. Helper tables

### 9.1 Spacing radius (`h92.hot`): d≤.1 → .4, ≤.3 → .5, ≤.5 → .6, else .75 (axis‑aligned box + Euclidean).
### 9.2 `within(point, list, r)` (`h92.l20`): box |Δx|,|Δy| ≤ r and Euclidean ≤ r.
### 9.3 Selection: top‑8 truncation before roulette in `pick`; no truncation in start‑feet scorer.
### 9.4 Grip `tlk.y6y` (only used by the server‑model engine)

`grip = clamp(f(type,size) · (1.75 − 2·l2z/255), 0, 1)` with f:

| type | size <500 | 500–749 | 750–999 | 1000–1199 | 1200–1499 | 1500–1999 | ≥2000 |
|---|---|---|---|---|---|---|---|
| Jug | .5 | .75 | 1.0 | 1.2 | 1.5 | 2.0 | 2.0 |
| Edge | .2 | .3 | .5 | 1.0 | 1.0 | 1.5 | 1.5 |
| Crimp | 0 | .1 | .2 | .3 | .3 | .5 | .5 |
| Sloper | .2 | .3 | 1.0 | 1.5 | 1.5 | 2.0 | 2.0 |
| Pinch | .2 | .3 | .5 | .75 | .75 | 1.0 | 1.0 |
| Pocket | 0 | 0 | .1 | .1 | .1 | .2 | .2 |
| Crack | .1 | .3 | .75 | 1.0 | 1.0 | 1.5 | 1.5 |
| none | .1 | .2 | .3 | .4 | .5 | .75 | 1.0 |

---

## 10. The other engine (server‑model walls) – not used for user walls

When the wall has a server binary model (`eg3`, holds as `xon` with true 3D mm coordinates, per‑hold surface angles, precomputed difficulty 0..1, hold groups 16/17/18 that mark allowed start/finish sets, own grade range `xjr`), `z2a.gj1` runs `hu0.qro` (same planner) and then `q5z.q4u(path)` which expands **body states** `ncz/dty` (two hands + up to four contact points) with `ldf.wj9`, scoring moves with `vz4.ujk(from,to,…)` (uses `tlk.y6y` grip) and `dhu.yn` (uses hold size). That engine was located but not decoded in detail.

---

## 11. Known quirks / bugs (reproduce them if you want identical output)

1. Code 72 normalises to **0.675** (between 0.625 and 0.75 – likely a typo for 0.625).
2. `s4_.ujk(88)` and `s4_.yn(192)` fall through to the default 0.5.
3. Feature 109 uses `atan2(y − x, midY − midX)` instead of `atan2(y − midY, x − midX)`; the "second neighbour" is actually the **third** nearest.
4. Start‑feet offset compares the full direction value with 14/224/56 using equality; UI directions are single bits, so the offset is always (0,0).
5. Penalty type check compares `hold.type ≠ typeSum`; selecting ≥2 types penalises **every** hold (the selection factor f13 uses `&` correctly).
6. `xtj` tolerance column is never read; planner uses a fixed ±0.5 window and ±.175/.325 density tolerances.
7. Hold size has no effect on photo walls.
8. Rule flags (Sit Start, No Matching, No Hooks, Free Kicker, Chip Sets, Custom Rules) and style tags are not consumed by the generator.
9. Planner receives the *original* forced map; the sequencer uses the randomly reduced one (6.2).
10. Anti‑tamper: if tampering is detected the NN factor becomes −1 / random, f19 becomes constant 0.5, circuit checkpoint promotion may be skipped. All tables above are the *untampered* path.

---

## 12. Compact reconstruction pseudocode

```
generate(wall, s):
    G     = buildGraph(wall)                       # §4
    paths = planPaths(G, s)                        # §5
    P     = normalise(wall.holds)                  # §6.1
    F     = reduceForced(s.forced, s)              # §6.2
    pts   = resample(paths[0], s)                  # §6.3
    best  = null
    repeat 5:
        je = State(P \ F)
        addStarts(je, F, pts.first)                # NetA / forced
        addFinish(je, F, pts.last)                 # NetB / forced
        maybeSecondStart(je)
        if feetMode ∉ {Open, None}: startFeet(je, pts)
        maybeExtraFinish(je)
        addForcedZones(je, F, pts)
        for p in middle(pts): pick(je, 40, NetC, p)
        if circuit: promoteCheckpoints(je)
        fillGaps(je)                               # NetC at midpoints
        if feetMode ∉ {Open, None}: extraFeet(je)  # NetD with spacing
        pen = penalty(je)
        best = argmin(best, (je, pen)); if pen == 0: break
    return best.holds with roles
```

---

## 13. What the developer has said in public

u/Altitude3003, April 2021 – March 2026, mainly r/climbharder and r/homewalls. He has repeatedly declined to describe the internals ("I cannot go too much into detail", "I cannot unfortunately share too many details"). He also did not answer a direct question about hold parameters, the optimisation function, or whether generated problems are checked for being doable ([r/climbing, Jul 2021](https://www.reddit.com/r/climbing/comments/orgxf1/sharing_some_experimental_artificial_intelligence/)). Nothing here is a spec. It is what he claimed, checked against 2.1.1.

### 13.1 Statements the code agrees with

- **The grade is an input, not a measurement of the climb.** Jan 2026 he edited his own post, changing "automatic Grading" to "real Grade selection", and wrote that the app "works in the reverse way by asking you for a Grade and then generating climbs based on it." There is no grade for a climb the user sets by hand. He called reliable automatic grading "a very hard task" and "too early." This is §3.2: `whh.iyx` maps the Difficulty slider onto a Font/V code. In April 2021 the slider was deliberately unlabelled, because "60% might be something like V5 to V10, depending on the quality of the holds," and a crimp-only wall might start at a stiff V4. He wanted the top of the slider to feel like about grade 8 on every wall, and said a real grade cannot be predicted from the photo plus the user's hold labels, because hold quality changes the grade even when the movement stays the same. The default clamp in §3.2 is 4 … 8A+ (V0 … V12).
- **Training data was a small set he built himself**, "mainly on my own wall but also analyzing and replicating movement patterns of known boulder problems to keep a reference for the grades," with his own training tooling. Oct 2021: "I wish it was as simple as dragging some pre-made problems into Tensorflow." A V8 dyno on jugs would poison any attempt to learn hold difficulty from problem grades, which is why he rejected that. The four nets in §8 are tiny hand-sized MLPs, which fits a hand-built set. The training procedure itself is not in the APK.
- **Free-tier hold difficulty stopped at Foot / Easy / Medium / Hard on purpose.** April 2021, after a user pointed out that a sidepull cannot be crimped from above: "I tried a lot of things but ultimately the Easy/Medium/Hard split was the one that worked best for user defined walls." Pro (Oct 2021) then added the attributes he names as actually feeding generation: direction, hold type, and finer difficulty, "including for footholds." He still said, in Jan 2026, that even with those "the generation is still not perfect (with varying levels of success depending on the hold layout and wall shape)."
- **Size is a marker-circle control, not a generation input.** When users asked for smaller circles so clustered holds could be marked, he pointed at a Pro wall-editor mode "for setting the size of the circles" ([Instagram demo](https://www.instagram.com/p/CaMdMTUAAV1/)). He never lists size next to direction, type, and difficulty. That matches §2.5: size only reaches the grip table, which photo walls never read.
- **Feet follow hands is the default contract.** April 2021: blue holds are hands and feet, yellow holds are feet only. A single green start, or a single red finish, means both hands match that hold (he confirmed this in Mar 2022, and said some of those match starts "will be pretty hard"). The generator does not emit a match flag. One start hold is just one start hold, and the climbing rule is applied by the UI. "Open feet" (any hold may be a foot) was not in the app in April 2021; he said he already climbed that way himself. It is flag 4 in §3.1, and it skips foot generation.
- **Length is how vertical a problem is.** Mar 2022, about his own 8×8 ft wall: "short problems are mostly vertical and direct, while longer problems use more traverse movements." Forcing a traverse is Pro: pick start and finish holds, or draw a path. Draw Path "allows you to select a path that the generation will try to match." That is the line snap in §5 (`hu0.jhw`) and the length target in §5.2. He also said there are "mechanisms to try to avoid shortcuts," which still fail on very small walls. Those are the height-loss and top-reach penalties in §5.6.
- **Move order is not generated.** Mar 2022 he said he had not implemented hold order, "introducing instead the zone mechanism to define circuits," and that circuits cannot make more than one loop. Numbered holds, which could also express a forced sequence, were an experiment he mentioned in Nov 2024. 2.1.1 still uses zones (§6.2).
- **Rules are labels.** Nov 2024: free-text rules are ambiguous once a wall has many users, so he "tried to cover the most common rules with tags," shown at the top of the climb. Per-hold exceptions ("set feet, except this one hand hold") "would indeed not be easily integrated." Most people he talked to "prefer to have a simpler set of rules, since going too much in detail can make the problems be a bit too contrived." That is why the rule bits and style tags in §3.1 are stored and displayed and then ignored.
- **The generator is meant to be loose.** April 2021, answering "sometimes good, sometimes utter bullshit": the algorithm "works with limited information about the holds so it can generate some combinations that are a bit too futuristic." He "deliberately tried to let the algorithm a bit loose, rather than generating safe but boring ladder problems." His own use, repeated in 2021, 2024 and 2026, is to reroll until a sequence looks good and then edit a few holds. Roulette selection plus five retries (§6.4) is that design.

### 13.2 Limitations he has acknowledged, and the code behind them

- **Footholds.** April 2021: "not ideal … especially on the lower end of the difficulty slider," and "even with kickers right now it can be quite harsh." Oct 2021, after Pro shipped direction and type: problems "still need a few tweaks, especially to the footholds." Foot placement is the separate scorer in §6.5 (not the hand picker), and Net D in §8.4.
- **Bad starts and bad geometry.** Works best on "single panel walls, without too much geometry," and on "relatively dense overhanging walls." "Normal gym walls, especially on vertical sections, would be too sparse." Caves with several panels were a plan, not a feature. The photo graph (§4) is one plane at one angle.
- **Span is not a body size.** Nov 2024: the algorithm "is not really designed to work for kids"; the lowest Hold Span "might" work "although they may still be a bit reachy." There is no climber height or wingspan in the settings. Span only changes the resample step (§6.3).
- **Walls that get reset often.** Nov 2024: the data model "does not adapt well to constantly changing walls" and fits a layout changed "once a year." He had tried automatic hold detection; it needs "a separate set of details" and "accuracy … can vary greatly depending on the layout of the wall and the type of holds." It is not in 2.1.1. Image replacement was, in Oct 2021, a manual rectangle fit that "works best when you need to just add holds."

### 13.3 Setup errors he says produce bad climbs

These are consequences of the single scale in §4, `scale = (maxY − minY) / heightMm`, then `mm = px / scale`.

- **Height is the length of the wood, including the kickboard, not the vertical rise.** A MoonBoard is "13 ft (~3.9 m)" of panel, not the shorter vertical measurement. Entering the smaller number shrinks every millimetre coordinate, so the ~0.75 m sample step covers more of the photo and the moves come out as the "massive spans" a user reported on a ~3 m, 40–45° wall even with Span at Very Short. He suggests checking against your own height, 4×8 ft panel seams, or bolt-hole counts, and editing it later in Wall Details.
- **The main panel has to be a straight rectangle in the photo.** Kneel below the wall and tilt up so the side edges of the main panel are straight. A picture taken standing, straight on, foreshortens the wall. "The markers do not need to have pixel perfect precision" — he says the algorithm has an error margin — but a panel tilted forward or sideways "can result in some inconsistent moves … always generating very reachy moves at the start." A kicker "can be fairly distorted," because "the proportions for the first foot-only rows are not as important."
- **Portrait photos with a lot of mattress or ceiling** made marker circles the wrong size (Mar 2022). His workaround was to crop that empty space out. That is display/setup, not the picker.
- **Topping out** has no special hold. April 2021 he told users to drop fake holds on the top edge, and later to force those as the finish.

### 13.4 Later plans that are not this algorithm

- **A second, paid, per-wall model.** Jan 2026: a "DIY" model (this report) stays in the app. A separate "advanced" model, priced higher because each wall is set up for the user, is meant to add quality, non-flat shapes, and grade selection. He was recruiting wall photos at boulderbot.io/advanced-model-testing.html. The server-model engine in §10 is the closest thing already in 2.1.1, and it was not decoded here.
- **Variable-angle grading.** Mar 2026 ([r/climbharder](https://www.reddit.com/r/climbharder/comments/1s0hbml/looking_for_opinions_on_grading_and_logging_for/)) he was still designing how logs and grades should work across angles. He wrote that he doubts a simple angle translation, "as different hold types and movements can translate differently … (e.g. slopers versus incuts) especially with large differences (e.g. 60° vs 20°)." 2.1.1 already does the thing he is doubting, and it ignores hold type: §3 lowers the difficulty used for picking by `0.2·(angle − 130)/40` and shifts the displayed grade by the fixed `r72` table. He did not identify that table as his.
- **Other app bugs he confirmed**, unrelated to the picker: Android crashing if wall setup was resumed after the process had been backgrounded (Apr 2021); iOS importing some photos with the wrong orientation (Mar 2022). Shared logic is a Kotlin module "compiled into low level binaries," with native UI on each platform, which is why the Android package is the obfuscated `b` this report is read from.

### 13.5 Sources

| date | thread |
|---|---|
| Apr 2021 | [First release, r/climbharder](https://www.reddit.com/r/climbharder/comments/miitt8/i_trained_a_procedural_generation_model_to_create/) |
| Jul 2021 | [Experimental Pro features, r/climbing](https://www.reddit.com/r/climbing/comments/orgxf1/sharing_some_experimental_artificial_intelligence/) |
| Oct 2021 | [Pro release, r/climbharder](https://www.reddit.com/r/climbharder/comments/q6sy8e/i_released_the_pro_version_of_boulderbot_for/) |
| Mar 2022 | [iOS release, r/climbharder](https://www.reddit.com/r/climbharder/comments/tadouf/the_boulderbot_app_for_home_climbing_walls_and/) |
| Nov 2024 | [Version 2.0, r/climbharder](https://www.reddit.com/r/climbharder/comments/1h24vgk/i_released_version_20_of_boulderbot_an_app_for/) |
| Jan 2026 | [Advanced model, r/homewalls](https://www.reddit.com/r/homewalls/comments/1qa3eum/looking_for_sample_images_for_a_new_advanced/) |
| Mar 2026 | [Variable-angle grading, r/climbharder](https://www.reddit.com/r/climbharder/comments/1s0hbml/looking_for_opinions_on_grading_and_logging_for/) |

---

## Appendix A – obfuscated name map

| name | meaning |
|---|---|
| `pte` | wall (photo, height mm `l20`, angle `q4u`) |
| `gkh` | hold |
| `nz7` | wall graph (nodes `wj9`, model `rj`, settings `hot`, min/max grade `l20`/`q4u`, server model flag `iyx`) |
| `tlk` | graph node (x `rj`, vertical y `hot`, depth z `kmg`, type `l20`, dir angle `q4u`, wall angle `liq`, edges `if3`, grip `y6y`, l2z, a4e, qc) |
| `w1l` | settings |
| `l3c` | normalised hold (x `rj`, y `hot`, depthBelowTop `kmg`, hd `l20`, role `q4u`) |
| `je` | sequencer state (avail `rj`, chosen `kmg`, settings `hot`, circuit `wj9`) |
| `hu0.qro` / `hu0.q4u` / `hu0.uia` / `hu0.jhw` | planner / walk / node filter / line snapping |
| `hke.olk` + `qav` | length target |
| `h92.q4u` / `h92.wj9` / `h92.kmg` / `h92.hot` / `h92.l20` | sequencer / pick / NN features / spacing filter / radius query |
| `lus`, `sb5.ujk`, `t5(23..26)` | network weights / evaluator / net wrappers (A, B, C, D) |
| `s4_.w86` | roulette selection |
| `s4_.ujk`, `s4_.yn` | code → planner difficulty / secondary difficulty |
| `pke.liq` | direction reach factor |
| `xtj` | grade → target hold difficulty |
| `ipr`, `vzz`, `whh.iyx`, `rl0.if3`, `r72` | grade lists, grade name, d→grade, clamped grade, angle grade shift |
| `drf`, `ccm.hot` | settings store / preferences |
| `z2a.gj1` | engine dispatcher |
| `uue` | graph builder (server model or photo fallback) |
| `q5z`, `ldf`, `vz4`, `dhu`, `ncz`, `dty` | server‑model body‑simulation engine |
