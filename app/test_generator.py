"""Self-check for the generator: python -m app.test_generator"""
import random
import time

from app.generator import generate, run_net, dist, GEN_HD


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
        top_start = min(by_id[h['id']]['y'] for h in r['holds'] if h['role'] == 10)
        low_finish = max(by_id[h['id']]['y'] for h in r['holds'] if h['role'] == 20)
        assert low_finish < top_start, (seed, r)  # finish above start (image y grows downward)
    circ = generate(holds, wall, {'difficulty': .4, 'circuit': True}, seed=3)
    assert any(h['role'] == 30 for h in circ['holds'])
    trav = generate(holds, wall, {'difficulty': .4, 'traverse': True, 'length': .8}, seed=4)
    assert trav['holds']
    print(f'ok: {n} problems in {time.monotonic() - t0:.1f}s, e.g. {r["grade"]}, {len(r["holds"])} holds, penalty {r["penalty"]}')


if __name__ == '__main__':
    main()
