"""Climb names, ported from BoulderBot 2.2.0.

A weighted template like '#Jobs from (#City|#Country)' is filled from word lists (names.json):
  #Key      random word from list `key`; a capital K capitalises it, a lowercase k lowercases its first letter
  (a|b|3:c) weighted choice (default weight 1), expanded recursively
A name never repeats a word within one category. Names longer than 24 characters are re-rolled.
Plurals and other derived lists use BoulderBot's own suffix rules, quirks included ("midwifes").
"""
import json
import random
import re
from pathlib import Path

_DATA = json.loads((Path(__file__).parent / 'names.json').read_text())
L = _DATA['lists']


def _animals(w):
    if w == 'Mouse':
        return 'Mice'
    if w in {'Bison', 'Cattle', 'Deer', 'Elk', 'Moose', 'Reindeer', 'Sheep', 'Shrimp', 'Triceratops', 'Tyrannosaurus'}:
        return w
    if w.endswith(('ay', 'ey', 'oy', 'uy', 'iy')):
        return w + 's'
    if w.endswith('y'):
        return w[:-1] + 'ies'
    if w.endswith(('s', 'sh', 'x', 'ch')):
        return w + 'es'
    if w.endswith('lf'):
        return w[:-1] + 'ves'
    return w + 's'


def _jobs(w):
    if w.endswith('man'):
        return w[:-3] + 'men'
    if w.endswith('ry'):
        return w[:-1] + 'ies'
    return w + ('es' if w.endswith(('ch', 'ss')) else 's')


def _ing(w):
    for end, add in (('n', 'ning'), ('im', 'ming'), ('it', 'ting')):
        if w.endswith(end):
            return w + add
    if w.endswith('e'):
        return w[:-1] + 'ing'
    if w.endswith('og'):
        return w + 'ging'
    return w + ('king' if w.endswith(('ek', 'c')) else 'ing')


def _es_plural(w):
    if w.endswith(('e', 'o', 'a', 'f')):
        return w + 's'
    if w.endswith(('r', 'l', 'n')):
        return w + 'es'
    return w[:-1] + 'ces' if w.endswith('z') else w


def _es_fem(w):
    for m, f in (('o', 'a'), ('os', 'as'), ('one', 'ona'), ('ones', 'onas')):
        if w.endswith(m):
            return w[:-len(m)] + f
    return w


_digits, _numbers = [str(i) for i in range(10)], [str(i) for i in range(100)]
L.update(
    adjectiven=[w for w in L['adjective'] if not w.endswith('ing')],
    animals=[_animals(w) for w in L['animal']],
    animalnv=[w for w in L['animal'] if w[0] not in 'AEIOUJ'],  # for "A #AnimalNV"
    jobs=[_jobs(w) for w in L['job']],
    jobnv=[w for w in L['job'] if w[0] not in 'aeiouj'],
    sportinfinite=[_ing(w) for w in L['sport']],
    shapes=[w + ('es' if w.endswith('s') else 's') for w in L['shape']],
    digit=_digits, digitp=[d for d in _digits if d != '1'], digitt=_digits[2:],
    number=_numbers, numberp=[n for n in _numbers if n != '1'], numbert=_numbers[2:],
    year=[str(y) for y in range(1800, 2201)],
    spanishnamemp=[_es_plural(w) for w in L['spanishnamem']],
    spanishnamefp=[_es_plural(w) for w in L['spanishnamef']],
    spanishadjectivemp=[_es_plural(w) for w in L['spanishadjectivem']],
    spanishadjectivef=[_es_fem(w) for w in L['spanishadjectivem']],
)
L['spanishadjectivefp'] = [_es_fem(w) for w in L['spanishadjectivemp']]


def parse(t):
    """Template -> nodes: str literal, (key, capitalise) slot, or [(nodes, weight)] choice."""
    nodes, lit, i = [], '', 0
    while i < len(t):
        c = t[i]
        if c not in '(#':
            lit += c
            i += 1
            continue
        if lit:
            nodes.append(lit)
            lit = ''
        if c == '(':
            body = t[i + 1:].split(')', 1)[0]  # no nesting, as in the original
            opts = {}  # keyed by text: duplicate options collapse, as they do in BoulderBot
            for o in body.split('|'):
                w, o = o.split(':', 1) if re.fullmatch(r'-?\d+(?:\.\d+)?:.*', o) else ('1', o)
                opts[o] = float(w)
            nodes.append([(parse(o), w) for o, w in opts.items()])
            i += len(body) + 2
        else:
            key = re.match(r'[A-Za-z]*', t[i + 1:]).group()
            L[key.lower()]  # unknown category: fail at import, not mid-generation
            nodes.append((key.lower(), key[0].isupper()))
            i += len(key) + 1
    if lit.strip():
        nodes.append(lit)
    return nodes


TEMPLATES = [parse(t) for t, _ in _DATA['templates']]
WEIGHTS = [w for _, w in _DATA['templates']]


def expand(nodes, rnd, used):
    out = []
    for n in nodes:
        if isinstance(n, str):
            out.append(n)
        elif isinstance(n, list):
            out.append(expand(rnd.choices([o for o, _ in n], [w for _, w in n])[0], rnd, used))
        else:
            key, cap = n
            seen = used.setdefault(key, set())
            w = rnd.choice(L[key])
            for _ in range(100):
                if w not in seen:
                    break
                w = rnd.choice(L[key])
            seen.add(w)
            out.append(w[:1].upper() + w[1:] if cap else w[:1].lower() + w[1:])
    return ''.join(out)


def generate(taken=(), rnd=random):
    """A name not in `taken`, at most 24 characters. Gives up after 1000 tries and returns the last one."""
    for _ in range(1000):
        name = expand(rnd.choices(TEMPLATES, WEIGHTS)[0], rnd, {})
        if name not in taken and len(name) <= 24:
            return name
    return name
