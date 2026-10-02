"""Self-check for the generator: python -m app.test_generator"""
import math
import random
import time

from app import beta
from app.generator import generate, run_net


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
    check_kinematic(holds, wall)
    print(f'ok: {n} problems in {time.monotonic() - t0:.1f}s, e.g. {r["grade"]}, {len(r["holds"])} holds, penalty {r["penalty"]}')


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
