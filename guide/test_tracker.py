"""Tracker scenarios without UI or game. Run: python -X utf8 test_tracker.py"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import DATA, GuideData, Tracker  # noqa: E402

gd = GuideData()
idx = json.load(open(os.path.join(DATA, 'textindex.json'), encoding='utf-8'))
RECT = (0, 0, 1280, 720)
fails = 0


def check(name, cond, extra=''):
    global fails
    fails += not cond
    print('OK  ' if cond else 'FAIL', name, extra)


def dialog(text):
    return [(text, (100, 600, 900, 640))]


def line_of(f, b):
    for lf, lb, _, t in idx['lines']:
        if lf == f and lb == b and len(t) >= 8:
            return t
    return None


tr = Tracker(gd, '11')
steps = tr.steps

# 1. repeated map: map17 three times -> each visit hits the next occurrence
m17 = [i for i, s in enumerate(steps) if s['kind'] == 'map' and s['map'] == 'map17']
tr.ptr = m17[0]
got = []
for _ in m17:
    k, i = tr.classify(RECT, [(o, (0, 200, 0, 0)) for o in steps[m17[0]]['options']])
    got.append(i)
    tr.leave(k, i)
check('map17 occurrences in order', got == m17, f'{got} vs {m17}')

# 2. deduction retry: wrong-answer reaction rolls back to the question
d = next(i for i, s in enumerate(steps) if s['kind'] == 'deduc' and line_of(s['file'], s['wrong_block']))
s = steps[d]
tr.ptr = d
tr.leave('deduc', d)
tr.track_dialog(RECT, dialog(line_of(s['file'], s['wrong_block'])))
check('wrong deduction -> back to question', tr.ptr == d, f'ptr={tr.ptr} d={d}')
if s.get('right_block') and line_of(s['file'], s['right_block']):
    tr.leave('deduc', d)
    tr.track_dialog(RECT, dialog(line_of(s['file'], s['right_block'])))
    check('right deduction -> moves on', tr.ptr >= d + 1 and tr.pending_deduc is None, f'ptr={tr.ptr}')

# 3. backlog screen (many long lines) does not move the pointer
tr.ptr = 5
far = [t for f, b, _, t in idx['lines'] if f.startswith('19a') and len(t) >= 10][:6]
tr.track_dialog(RECT, [(t, (100, 400 + 40 * k, 900, 430 + 40 * k)) for k, t in enumerate(far)])
check('backlog ignored', tr.ptr == 5, f'ptr={tr.ptr}')

# 4. select seen again after loading an older save -> jumps back to it
si = [i for i, s in enumerate(steps) if s['kind'] == 'select'][2]
tr.ptr = si + 20
k, i = tr.classify(RECT, [(o, (0, 200, 0, 0)) for o in steps[si]['options']])
check('older select found', (k, i) == ('select', si), f'{k} {i} vs {si}')

# 5. person list needs whole-line names; dialogue containing names is not a list
names = json.load(open(os.path.join(DATA, 'names.json'), encoding='utf-8'))['person']
plist = [(names[str(c)], (0, 100 + 30 * c, 0, 0)) for c in (1, 2, 5, 6, 7)]
check('person list detected', gd.list_screen(plist) == '人物')
check('dialogue not a list', gd.list_screen([(f'{names["1"]}和{names["2"]}說{names["5"]}找{names["6"]}', (0, 600, 0, 0))]) is None)

print('failures:', fails)
sys.exit(1 if fails else 0)
