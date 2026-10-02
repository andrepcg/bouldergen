# AGENTS.md

BoulderGen is a self-hosted web app for a home spray wall:
- photograph the wall
- straighten the photo
- auto-detect holds, then fix them up on a phone
- generate boulder problems with a port of the BoulderBot algorithm

It runs as one Docker container on a LAN. It is single-user, with no auth.

## Layout

```
app/main.py            FastAPI routes, SQLite storage, static serving
app/detect.py          photo straightening + OpenCV hold detection
app/generator.py       BoulderBot port: graph, path planner, hold sequencer, 4 MLPs, penalty, grades
app/beta.py            "Kinematic" engine: A* over body states (LH, RH, LF, RF), returns explicit beta
app/test_generator.py  assert-based self-check (runs in CI)
static/                frontend: index.html, app.js, style.css — vanilla JS, no build step
boulderbot-research.md reverse-engineering spec the generator follows (§ refs in code point here)
Dockerfile, docker-compose.yml, .github/workflows/docker.yml
```

## Run / test

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # needs Python ≤3.12 (pillow-heif wheels)
DATA_DIR=data .venv/bin/uvicorn app.main:app --reload                 # http://localhost:8000
.venv/bin/python -m app.test_generator                                # generator self-check
.venv/bin/python -m app.detect photo.jpg x1,y1,...,x8,y8 W H K out.png # detection overlay; corners as 0..1 fractions
docker build -t bouldergen . && docker run -p 8000:8000 -v bouldergen-data:/data bouldergen
```

To iterate on the frontend in Docker without rebuilding, bind-mount `-v "$PWD/static:/srv/static:ro"`.

**Deploy:** a push to `main` triggers CI. CI runs the self-check, then builds and pushes `ghcr.io/andrepcg/bouldergen:latest`. In Portainer, the user pastes in `docker-compose.yml`. Don't deploy by SSH.

## Core conventions

- **Units are millimetres everywhere after rectification.** The rectified image is 1 px = 1 mm.
  - The main panel sits on top. The kicker is stacked below it, starting at `y = wall.height`.
  - Hold `x, y` values are in mm in that image, with y pointing down.
  - The frontend SVG `viewBox` is in the same mm coordinates, so overlays need no conversion.
- **Angles use BoulderBot's convention:** 90 = vertical, 180 = roof. The UI shows overhang (`angle − 90`).
  - The wall has `min_angle`, `max_angle`, and `ref_angle` (the angle the hold grades were set at).
- **Hold record:**
  - `{id, x, y, r, area, poly, color, kind: 'hold'|'volume', difficulty, type, direction}`.
  - `difficulty` codes: 24/32/40 easy, 56/64/72 medium, 88/96/104 hard, 192/200/208 foot.
  - `type` and `direction` are the bitmasks from research §2.3–2.4.
  - Volumes are drawn but excluded from generation.
- **Roles in a problem:** 10 start, 20 finish, 30 zone, 40 hand, 50 foot.
- **Storage:** SQLite with two JSON tables, `walls(id, data)` and `problems(id, wall_id, data)`.
  - A wall's holds live inside the wall JSON. The editor PUTs the whole array.
  - Images are stored in `$DATA_DIR/images/<wall_id>/`.

## Generator (app/generator.py)

The generator is a faithful port of `boulderbot-research.md` §2–§9. Keep the § comments in sync when editing.

Two stages:
1. **Planner (mm):** a random walk over a hold graph (edges ≤ 1750 mm), scored for height loss, length, top reach and difficulty density.
2. **Sequencer (metres):** resamples the path, picks holds by roulette over the factor tables × MLP output, adds feet, and fills gaps. It makes 5 attempts and keeps the lowest penalty.

**Quirks, deliberately kept.** The MLP weights and tables were tuned with them:
- code 72 → 0.675
- the 88/192 fall-throughs
- feature 109 `atan2(y − x, …)` with the "3rd nearest" hold
- Java half-up rounding (`jround`)

**Fixed:**
- §11.4: the start-feet direction test is now bitwise.
- §11.5: the penalty type check is now bitwise.

**Deviations from the source:**
- The start/top region cells are keyed by surface height, not depth z, so vertical walls work. It's marked `ponytail:`.
- The planner returns the first path found, since only `results[0]` was ever used.
- Kicker nodes are treated as vertical.

**Grade:** the grade is an input, not a measurement. The Difficulty slider maps to a Font/V grade, shifted by the angle table `R72`. The client mirrors this in `gradeLabel()` using `/api/meta`.

Any change to the generator must keep `python -m app.test_generator` passing.

## Kinematic engine (app/beta.py)

You pick the engine with `settings.engine` (`'boulderbot'` is the default, or `'kinematic'`), dispatched in `main.generate`. Both engines return the same shape. Kinematic also returns `beta: {start, moves}`, and hand holds carry `n`, their reach order.

**State:** `(LH, RH, LF, RF)` hold indices, in metres, with y measured up from the floor.

**Moves:** compound. Feet adjust first (at most two), then one hand reaches. Every intermediate pose must be legal.

**`legal()` checks, body only:**
- feet stay below hands
- the hands aren't compressed too close to the feet
- no crossed feet
- the hip can reach both feet and the shoulders both hands (`pose()` runs a 3×3 hip search)
- no barn door: the centre of mass sits within the contacts sideways
- every hand pulls in its hold's direction

**`Search.ok()` adds the per-problem comfort limits:**
- maximum hand gap
- maximum sideways lean between the hands' midpoint and the feet's midpoint

**Per-move limits:** a hard `max_move` and a preferred `pref` hand move, both scaling with difficulty and span. Stretching past `pref` costs extra.

**Starts are low.** Sit or crouch start: hands at 0.3–0.62 × climber height above the lowest feet, with the feet on the lowest footholds under the hands.

The self-check replays every kinematic beta through `legal()`. A user report ("V0" with a 1.4 m diagonal stretch from a lean) is what set the gap and lean limits. Tune those numbers against real climbing, not just the tests.

## Detection (app/detect.py)

Tuned on a black-painted wall with coloured PU holds:

| Step | What it does |
|---|---|
| Colour mask | HSV saturation/brightness threshold, split into hue bins so holds on a volume come out separate |
| White/grey holds | Brighter than the local background (median-blurred V). This makes it robust to glare and to varnished empty T-nut holes. |
| Black holds | Darker than the background, with a large minimum area and a solidity filter to reject T-nut smudges |
| Filters | Drop blobs touching the image border (brackets, frame) and slivers narrower than 25 mm |
| Merge | Merge fragments whose equivalent circles overlap: one hold split across hue bins or by its bolt |
| Defaults | Kicker → Foot. Otherwise difficulty from the size tercile (large = easy). Type Edge, direction ↓. |

On the reference photo, detection found 71/71 upper holds, 3/3 on the volume, and 8/10 kicker feet. The misses are faint grey or black holds, and the user adds those by tap. Thresholds live in `DEFAULTS` and are exposed as sliders under Setup → Detection sensitivity.

Re-straightening or re-detecting **replaces all hold edits**. The UI confirms first.

## Frontend (static/app.js)

- Hash router: `#/` and `#/wall/<id>/<gen|problems|holds|setup>`. The `stage` views (gen, holds) have a viewer plus a bottom panel; the `page` views scroll.
- `createViewer()` owns all wall interaction:
  - pinch/wheel zoom, pan, tap, handle drag, area select.
  - Page zoom is never used; the viewer has `touch-action: none`.
  - Taps resolve to the nearest hold within a finger-sized tolerance (`nearestHold`).
- `el()` builds DOM/SVG. Use `put()` / `add()` instead of the native `replaceChildren` / `append` whenever children can be `null`/`false`. The native calls render those as literal text.
- The holds panel has a fixed height on purpose, so the wall doesn't resize when the selection changes. Keep stage panels from changing height on tap.
- Overlay strokes use `vector-effect: non-scaling-stroke`, so they stay legible at any zoom.
- The server sends `Cache-Control: no-cache` on everything, so phones pick up new JS/CSS without a hard refresh.
- Per-viewer settings (generate sliders) live in `localStorage`, wrapped in try/catch.

## Style

- Keep it small: stdlib + FastAPI/OpenCV/Pillow on the backend, and no frontend dependencies or build step.
- Match the surrounding code's density. Comments explain *why*, not what.
- Mark deliberate shortcuts with a `ponytail:` comment naming the limit and the upgrade path.

## Not built yet (add when needed)

- Keeping hold attributes across a re-photo after a wall reset (match new detections to old holds within ~30 mm).
- GPU segmentation (SAM) for black or wooden holds.
- Drawing a line for the generator to follow (research §5.3 "From Line").
- Auth, logbook/ticks, and multi-panel walls.
