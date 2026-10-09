import json
import os
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

import cv2
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from app import beta, detect, generator, names

DATA = Path(os.environ.get('DATA_DIR', 'data'))
IMAGES = DATA / 'images'
IMAGES.mkdir(parents=True, exist_ok=True)
STATIC = Path(__file__).parent.parent / 'static'

db = sqlite3.connect(DATA / 'bouldergen.db', check_same_thread=False, isolation_level=None)
db.execute('CREATE TABLE IF NOT EXISTS walls (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
db.execute('CREATE TABLE IF NOT EXISTS problems (id TEXT PRIMARY KEY, wall_id TEXT NOT NULL, data TEXT NOT NULL)')

app = FastAPI(title='BoulderGen')


@app.middleware('http')
async def revalidate(request, call_next):
    """Make browsers revalidate (ETag) so app updates show up without a hard refresh."""
    response = await call_next(request)
    response.headers.setdefault('Cache-Control', 'no-cache')
    return response

# fields the client may change with PUT
WALL_FIELDS = {'name', 'width', 'height', 'kicker', 'ref_angle', 'min_angle', 'max_angle', 'corners', 'holds',
               'detect_params'}


def get_wall(wall_id):
    row = db.execute('SELECT data FROM walls WHERE id = ?', (wall_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Wall not found')
    return json.loads(row[0])


def save_wall(wall):
    db.execute('INSERT OR REPLACE INTO walls (id, data) VALUES (?, ?)', (wall['id'], json.dumps(wall)))
    return wall


@app.get('/api/meta')
def meta():
    return {'grades': [f'{g[1]} / {g[2]}' for g in generator.GRADES], 'grade_lo': generator.GRADE_LO,
            'grade_hi': generator.GRADE_HI, 'r72': generator.R72, 'detect_defaults': detect.DEFAULTS}


@app.get('/api/walls')
def list_walls():
    walls = [json.loads(r[0]) for r in db.execute('SELECT data FROM walls')]
    return [{k: w.get(k) for k in ('id', 'name', 'photo', 'rect')} for w in walls]


@app.post('/api/walls')
def create_wall(name: str = Form(...), photo: UploadFile = File(...)):
    wall_id = uuid.uuid4().hex[:10]
    folder = IMAGES / wall_id
    folder.mkdir()
    try:
        img = detect.load_image(photo.file)
    except Exception:
        shutil.rmtree(folder)
        raise HTTPException(400, 'Could not read that image')
    cv2.imwrite(str(folder / 'photo.jpg'), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    h, w = img.shape[:2]
    # angles: 90 = vertical .. 180 = roof (BoulderBot convention); UI shows overhang = angle - 90
    wall = {'id': wall_id, 'name': name, 'photo': f'/images/{wall_id}/photo.jpg', 'photo_size': [w, h],
            'rect': None, 'width': 2440, 'height': 2440, 'kicker': 300, 'ref_angle': 120, 'min_angle': 90,
            'max_angle': 140,
            'corners': {'main': [[.05 * w, .1 * h], [.95 * w, .1 * h], [.95 * w, .8 * h], [.05 * w, .8 * h]],
                        'kicker': [[.05 * w, .81 * h], [.95 * w, .81 * h], [.95 * w, .9 * h], [.05 * w, .9 * h]]},
            'holds': [], 'detect_params': {}}
    return save_wall(wall)


@app.get('/api/walls/{wall_id}')
def read_wall(wall_id: str):
    return get_wall(wall_id)


@app.put('/api/walls/{wall_id}')
def update_wall(wall_id: str, body: dict = Body(...)):
    wall = get_wall(wall_id)
    wall.update({k: v for k, v in body.items() if k in WALL_FIELDS})
    return save_wall(wall)


@app.delete('/api/walls/{wall_id}')
def delete_wall(wall_id: str):
    get_wall(wall_id)
    db.execute('DELETE FROM walls WHERE id = ?', (wall_id,))
    db.execute('DELETE FROM problems WHERE wall_id = ?', (wall_id,))
    shutil.rmtree(IMAGES / wall_id, ignore_errors=True)
    return {'ok': True}


@app.post('/api/walls/{wall_id}/rectify')
def rectify_wall(wall_id: str, body: dict = Body(default={})):
    """Apply new corners/dimensions and straighten the photo. Existing holds are moved to match; a new wall gets detection."""
    wall = get_wall(wall_id)
    geom = lambda w: (w['corners'], w['width'], w['height'], w['kicker'])
    old = geom(wall)
    wall.update({k: v for k, v in body.items() if k in WALL_FIELDS})
    if not wall['kicker'] or not wall['corners'].get('kicker'):
        wall['kicker'] = 0
    img = cv2.imread(str(IMAGES / wall_id / 'photo.jpg'))
    rect = detect.rectify(img, *geom(wall))
    wall['rect'] = f'/images/{wall_id}/rect.jpg?v={int(time.time())}'
    if not wall['holds']:
        cv2.imwrite(str(IMAGES / wall_id / 'rect.jpg'), rect, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return run_detect(wall, wall.get('detect_params') or {}, rect)
    move = detect.mover(old, geom(wall))
    wall['holds'] = detect.remap(wall['holds'], move)
    problems = [json.loads(r[0]) for r in db.execute('SELECT data FROM problems WHERE wall_id = ?', (wall_id,))]
    for p in problems:  # the stick figure's skeleton is in wall mm too
        for pose in filter(None, (p.get('beta') or {}).get('poses') or []):
            for k in ('com', 'hip', 'shoulder'):
                q = move([pose[k]], pose[k][1])
                if q is not None:
                    pose[k] = [round(q[0][0]), round(q[0][1])]
    # all or nothing: the image, holds and problems must agree
    tmp = IMAGES / wall_id / 'rect.tmp.jpg'
    cv2.imwrite(str(tmp), rect, [cv2.IMWRITE_JPEG_QUALITY, 85])
    db.execute('BEGIN')
    try:
        save_wall(wall)
        db.executemany('UPDATE problems SET data = ? WHERE id = ?', [(json.dumps(p), p['id']) for p in problems])
        os.replace(tmp, IMAGES / wall_id / 'rect.jpg')
        db.execute('COMMIT')
    except BaseException:
        db.execute('ROLLBACK')
        raise
    return wall


@app.post('/api/walls/{wall_id}/detect')
def detect_holds(wall_id: str, params: dict = Body(default={})):
    rect = cv2.imread(str(IMAGES / wall_id / 'rect.jpg'))
    if rect is None:
        raise HTTPException(400, 'Straighten the photo first')
    return run_detect(get_wall(wall_id), params, rect)


def run_detect(wall, params, rect):
    params = {k: float(v) for k, v in params.items() if k in detect.DEFAULTS}
    wall['detect_params'] = params
    wall['holds'] = detect.detect(rect, wall['height'], params)
    return save_wall(wall)


@app.post('/api/walls/{wall_id}/generate')
def generate(wall_id: str, settings: dict = Body(default={})):
    wall = get_wall(wall_id)
    try:
        engine = beta if settings.get('engine') == 'kinematic' else generator
        problem = engine.generate(wall['holds'], wall, settings)
    except ValueError as e:
        raise HTTPException(422, str(e))
    taken = {json.loads(r[0])['name'] for r in db.execute('SELECT data FROM problems WHERE wall_id = ?', (wall_id,))}
    problem['name'] = names.generate(taken)
    return problem


@app.get('/api/walls/{wall_id}/problems')
def list_problems(wall_id: str):
    rows = db.execute('SELECT data FROM problems WHERE wall_id = ?', (wall_id,))
    return sorted((json.loads(r[0]) for r in rows), key=lambda p: -p['created'])


def problem_fields(body):
    """The parts of a problem the client may set, on save and on update."""
    if not body.get('holds'):
        raise HTTPException(400, 'Problem has no holds')
    return {'name': str(body.get('name') or 'Untitled')[:80], 'grade': body.get('grade'),
            'grade_index': body.get('grade_index'), 'angle': body.get('angle'),
            'holds': [{'id': str(h['id']), 'role': int(h['role']), **({'n': int(h['n'])} if h.get('n') else {})}
                      for h in body['holds']],
            'engine': body.get('engine', 'boulderbot'), 'beta': body.get('beta')}


@app.post('/api/walls/{wall_id}/problems')
def save_problem(wall_id: str, body: dict = Body(...)):
    get_wall(wall_id)
    problem = {'id': uuid.uuid4().hex[:10], 'wall_id': wall_id, 'created': time.time(), **problem_fields(body)}
    db.execute('INSERT INTO problems (id, wall_id, data) VALUES (?, ?, ?)',
               (problem['id'], wall_id, json.dumps(problem)))
    return problem


@app.put('/api/problems/{problem_id}')
def update_problem(problem_id: str, body: dict = Body(...)):
    row = db.execute('SELECT data FROM problems WHERE id = ?', (problem_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Problem not found')
    problem = {**json.loads(row[0]), **problem_fields(body)}
    db.execute('UPDATE problems SET data = ? WHERE id = ?', (json.dumps(problem), problem_id))
    return problem


@app.delete('/api/problems/{problem_id}')
def delete_problem(problem_id: str):
    db.execute('DELETE FROM problems WHERE id = ?', (problem_id,))
    return {'ok': True}


app.mount('/images', StaticFiles(directory=IMAGES), name='images')
app.mount('/', StaticFiles(directory=STATIC, html=True), name='static')
