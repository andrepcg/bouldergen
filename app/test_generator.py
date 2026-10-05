"""Self-check for the generator: python -m app.test_generator"""
import math
import random
import time

from app import beta, names
from app.generator import build_graph, generate, plan_path, run_net


def synthetic_wall(seed=1):
    rnd = random.Random(seed)
    wall = {'width': 3000, 'height': 3200, 'kicker': 300, 'ref_angle': 120}
    holds, i = [], 0
    for y in range(150, 3400, 230):
        for x in range(150, 2900, 260):
            if rnd.random() < .45:
                continue
            code = 200 if y > 3200 else rnd.choice([32, 32, 64, 64, 64, 96, 200])
            holds.append({'id': f'h{i}', 'x': x + rnd.randint(-60, 60), 'y': y + rnd.randint(-60, 60),
                          'difficulty': code, 'type': rnd.choice([1, 2, 4, 8]),
                          'direction': rnd.choice([1, 1, 1, 2, 128, 16, 0])})
            i += 1
    return holds, wall


def main():
    # §8.3 measured behaviour of nets A and B
    assert abs(run_net('A', [.2]) - 1) < 1e-3
    assert abs(run_net('A', [.6]) - .5) < 1e-3
    assert abs(run_net('A', [1.1]) - 1) < 1e-3
    assert abs(run_net('A', [2.0]) - .099) < 2e-3
    assert run_net('B', [2.0, .1, 0]) > .99
    assert run_net('B', [2.0, 1.0, 0]) < .01

    holds, wall = synthetic_wall()
    by_id = {h['id']: h for h in holds}
    t0, n = time.monotonic(), 50
    for seed in range(n):
        rnd = random.Random(seed)
        s = {'difficulty': rnd.random(), 'length': rnd.random(), 'span': rnd.random(),
             'feet': rnd.choice(['follow', 'set', 'open', 'none']), 'angle': rnd.choice([90, 110, 120, 140])}
        r = generate(holds, wall, s, seed=seed)
        roles = [h['role'] for h in r['holds']]
        ids = [h['id'] for h in r['holds']]
        assert len(ids) == len(set(ids)) and all(i in by_id for i in ids), r
        assert 10 in roles and 20 in roles, roles
        # finish above the lowest start (image y grows downward). Not the highest: BoulderBot's
        # optional second start can occasionally land above the finish, as in the original.
        low_start = max(by_id[h['id']]['y'] for h in r['holds'] if h['role'] == 10)
        low_finish = max(by_id[h['id']]['y'] for h in r['holds'] if h['role'] == 20)
        assert low_finish < low_start, (seed, r)
    circ = generate(holds, wall, {'difficulty': .4, 'circuit': True}, seed=3)
    assert any(h['role'] == 30 for h in circ['holds'])
    trav = generate(holds, wall, {'difficulty': .4, 'traverse': True, 'length': .8}, seed=4)
    assert trav['holds']
    check_sit()
    check_kinematic(holds, wall)
    check_names()
    check_remap()
    print(f'ok: {n} problems in {time.monotonic() - t0:.1f}s, e.g. {r["grade"]}, {len(r["holds"])} holds, penalty {r["penalty"]}')


def check_sit():
    """Sit start skips the standing-reach bands, so the path begins within 500 mm of the bottom."""
    wall = {'height': 4200, 'kicker': 0, 'ref_angle': 90}
    # Bottoms are under 700 mm apart, so a standing start reaches the row 850 mm up. Later rows are 800 mm
    # apart, inside the walk's 500–1000 mm step, so the line can keep climbing.
    H = 4200
    rows = [100, 950, 1750, 2550, 3350, 4150]
    holds = [{'id': f'b{i}', 'x': x, 'y': H - 100, 'difficulty': 64, 'type': 2, 'direction': 1}
             for i, x in enumerate((500, 650))]
    holds += [{'id': f'h{i}', 'x': x, 'y': H - s, 'difficulty': 64, 'type': 2, 'direction': 1}
              for i, (x, s) in enumerate((x, s) for s in rows[1:] for x in (400, 550, 700, 850))]
    nodes, adj = build_graph(holds, wall, 90)
    base = {'forced': {}, 'target_diff': .5, 'circuit': False, 'traverse': False, 'length': .5, 'variation': 0}
    stand = plan_path(nodes, adj, {**base, 'sit': False}, random.Random(0))
    sat = plan_path(nodes, adj, {**base, 'sit': True}, random.Random(0))
    low = min(n.y for n in nodes.values())
    assert stand and nodes[stand[0]].y > low + 500
    assert sat and nodes[sat[0]].y <= low + 500
    # End to end, with kicker feet below: the sequencer's .75 m standing-start floor used to veto the low row.
    holds += [{'id': f'f{i}', 'x': x, 'y': H, 'difficulty': 200, 'type': 2, 'direction': 1} for i, x in enumerate((450, 750))]
    low_starts = lambda sit: sum(any(h['role'] == 10 and h['id'][0] == 'b' for h in generate(
        holds, wall, {'difficulty': .3, 'sit': sit}, seed=i)['holds']) for i in range(10))
    assert low_starts(True) >= 7


def check_names():
    """BoulderBot's suffix rules (quirks kept), template syntax, and the 24-character cap."""
    assert [names._animals(w) for w in ('Wolf', 'Mouse', 'Sheep', 'Monkey', 'Fly')] == ['Wolves', 'Mice', 'Sheep', 'Monkeys', 'Flies']
    assert [names._jobs(w) for w in ('midwife', 'fireman', 'secretary')] == ['midwifes', 'firemen', 'secretaries']
    assert [names._ing(w) for w in ('Boulder', 'Run', 'Dance', 'Jog')] == ['Bouldering', 'Running', 'Dancing', 'Jogging']
    assert names.parse('#Jobs from (#city|3:x)') == [('jobs', True), ' from ', [([('city', False)], 1), (['x'], 3)]]
    assert names.expand(names.parse('#animal and #Animal'), random.Random(0), {}).split(' and ')[0][0].islower()
    rnd = random.Random(0)
    made = [names.generate(rnd=rnd) for _ in range(500)]
    assert all(0 < len(n) <= 24 for n in made), made
    assert names.generate(set(made), random.Random(0)) not in made


def check_remap():
    """Changing the kicker height re-straightens without losing holds: panel holds stay put, kicker holds stretch."""
    from app.detect import mover, remap
    corners = {'main': [[0, 0], [1000, 0], [1000, 2000], [0, 2000]], 'kicker': [[0, 2000], [1000, 2000], [1000, 2300], [0, 2300]]}
    holds = [{'id': 'a', 'x': 500, 'y': 1000, 'r': 40, 'area': 5000, 'poly': [[480, 980], [520, 1020]]},
             {'id': 'k', 'x': 500, 'y': 2150, 'r': 40}]
    a, k = remap(holds, mover((corners, 1000, 2000, 300), (corners, 1000, 2000, 600)))
    assert (a['x'], a['y'], a['r'], a['area'], a['poly']) == (500, 1000, 40, 5000, [[480, 980], [520, 1020]])
    assert (k['x'], k['y'], k['r']) == (500, 2300, 57)  # halfway down a doubled kicker; r scales by sqrt(area)
    assert [h['id'] for h in remap(holds, mover((corners, 1000, 2000, 300), (corners, 1000, 2000, 0)))] == ['a']
    # changing a setting and changing it back is lossless
    skew = {**corners, 'main': [[30, 10], [990, 0], [1000, 2000], [0, 1990]]}
    there = (skew, 1200, 2100, 450)
    back = remap(remap(holds, mover((corners, 1000, 2000, 300), there)), mover(there, (corners, 1000, 2000, 300)))
    assert [(h['x'], h['y']) for h in back] == [(h['x'], h['y']) for h in holds], back


def check_kinematic(holds, wall):
    """Replay each kinematic beta: every intermediate body position must be legal for that climber."""
    hs = beta.to_holds(holds, wall)
    idx = {h.id: h.i for h in hs}
    made = 0
    for seed in range(30):
        s = {'engine': 'kinematic', 'difficulty': seed % 5 / 5, 'length': seed % 3 / 2, 'feet': ['follow', 'set'][seed % 2],
             'climber_height': 160 + seed % 4 * 10}
        try:
            r = beta.generate(holds, wall, s, seed=seed)
        except ValueError:
            continue
        made += 1
        body = beta.Body(s['climber_height'] / 100)
        theta, strength = math.radians(wall['ref_angle'] - 90), .7 + s['difficulty']
        b = r['beta']
        state = [idx[b['start'][k]] for k in beta.LIMBS]

        def check(tag):
            com = beta.legal(body, tuple(state), hs, False)
            assert com is not None, (seed, tag)
            assert beta.effort(state, hs, com, beta.feet_of(state, hs), theta, strength) <= beta.MAX_EFFORT, (seed, tag, 'too heavy')
        check('start')
        for m in b['moves']:
            state[beta.LIMBS.index(m['limb'])] = idx[m['hold']] if m['hold'] else beta.FREE  # None = flagging
            check(m)
        assert state[0] == state[1] and {'id': hs[state[0]].id, 'role': 20} in r['holds'], (seed, 'ends matched on the finish')
        roles = {h['id']: h['role'] for h in r['holds']}
        assert any(v == 10 for v in roles.values())
    # some synthetic seeds fail on purpose: set feet on a 30° wall of random, often hard holds
    # can exceed what the static load check allows a weak climber
    assert made >= 20, made


if __name__ == '__main__':
    main()
