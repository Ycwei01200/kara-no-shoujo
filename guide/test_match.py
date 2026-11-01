"""Offline tests for matching logic (no game needed). Run: python -X utf8 test_match.py"""
import json, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import GuideData, DATA

gd = GuideData()
idx = json.load(open(os.path.join(DATA, 'textindex.json'), encoding='utf-8'))
random.seed(1)
sample = random.sample([l for l in idx['lines'] if len(l[3]) >= 12], 400)
ok = part = 0
for f, b, nm, t in sample:
    m = gd.match_line(t.replace('，', ',').replace('……', '•'))          # OCR-like punctuation noise
    ok += bool(m and m[0][0] == f)
    m2 = gd.match_line(t[:max(6, len(t) // 2)])                        # typewriter: half line shown
    part += bool(m2 and any(c[0] == f for c in m2[:3]))
print(f'full line -> file: {ok}/400   half line -> file: {part}/400')
hit = 0
for f, b, nm, opts in idx['selects']:
    r = gd.match_select([(o, (0, 0, 0, 0)) for o in opts] + [('玲人', (0, 0, 0, 0))])
    hit += f'sel:{f}:{b}' in r
print(f'select screens identified: {hit}/{len(idx["selects"])}')
print('map screen:', gd.is_map_screen([(p, 0) for p in ['私立櫻羽女學院', '月世界', '井之頭公園', '新宿站前']]),
      'not map:', gd.is_map_screen([('玲人', 0), ('「嗯，倒是沒什麼問題……」', 0)]))
