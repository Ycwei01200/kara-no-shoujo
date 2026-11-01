"""Shared logic for the pet and the detail window: data, OCR worker, route tracker."""
import difflib
import json
import os
import re
import threading
import time
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
PHOTO = os.path.join(DATA, 'img', 'pc', 'tw', 'game', 'note', 'icon')

PUNCT = re.compile(r'[\s　「」『』（）()、，,。．.…‥・·•！!？?：:；;“”"‘’\'\-—―～~〈〉《》【】\[\]]+')


def norm(s):
    return PUNCT.sub('', s)


def whole_line(name, t):
    """OCR line t is (almost) exactly the label `name`."""
    return t == name or (name in t and len(t) <= len(name) + 2)


# ------------------------------------------------------------------ data
class GuideData:
    def __init__(self):
        self.routes = json.load(open(os.path.join(DATA, 'routes.json'), encoding='utf-8'))
        idx = json.load(open(os.path.join(DATA, 'textindex.json'), encoding='utf-8'))
        names = json.load(open(os.path.join(DATA, 'names.json'), encoding='utf-8'))
        self.places = {norm(v) for v in names['places'].values()}
        self.person_names = {norm(v) for v in names['person'].values() if len(norm(v)) >= 2}
        self.evid_names = {norm(v) for v in names['evidence'].values() if len(norm(v)) >= 3}
        self.lines = [(f, b, norm(t)) for f, b, _, t in idx['lines'] if len(norm(t)) >= 4]
        self.exact = defaultdict(list)
        self.tri = defaultdict(set)
        for i, (f, b, t) in enumerate(self.lines):
            self.exact[t].append(i)
            for k in range(len(t) - 2):
                self.tri[t[k:k + 3]].add(i)
        self.selects = [(f'sel:{f}:{b}', [norm(o) for o in opts]) for f, b, nm, opts in idx['selects']]

    def match_line(self, text):
        """All plausible script lines for an OCR'd dialogue string: [(file, block, score)]."""
        t = norm(text)
        if len(t) < 4:
            return []
        if t in self.exact:
            return [(self.lines[i][0], self.lines[i][1], 1.0) for i in self.exact[t]]
        cnt = defaultdict(int)
        grams = [t[k:k + 3] for k in range(len(t) - 2)]
        for g in grams:
            ids = self.tri.get(g)
            if ids and len(ids) < 400:
                for i in ids:
                    cnt[i] += 1
        if not cnt:
            return []
        top = max(cnt.values())
        if top / len(grams) < 0.5:
            return []
        best = [i for i, c in cnt.items() if c == top]
        best.sort(key=lambda i: -cnt[i] / max(1, len(self.lines[i][2]) - 2))
        return [(self.lines[i][0], self.lines[i][1], top / len(grams)) for i in best[:8]]

    @staticmethod
    def _opt_hit(o, t):
        if not o or not t:
            return False
        if o == t:
            return True
        if o in t and len(t) <= len(o) + (4 if len(o) >= 3 else 2):
            return True   # short options ('是的') tolerate a stray mark or two
        if len(o) >= 3 and len(t) >= 3:
            return difflib.SequenceMatcher(None, o, t).ratio() >= 0.8
        return False

    def match_select(self, ocr_lines):
        """Ids of selects whose options are all visible (each option ~ one OCR line)."""
        texts = [norm(t) for t, _ in ocr_lines if norm(t)]
        out = []
        for sid, opts in self.selects:
            if len(opts) >= 2 and all(any(self._opt_hit(o, t) for t in texts) for o in opts):
                out.append(sid)
        return out

    def visible_places(self, ocr_lines):
        texts = [norm(t) for t, _ in ocr_lines]
        return {p for p in self.places if any(whole_line(p, t) for t in texts)}

    def is_map_screen(self, ocr_lines):
        return len(self.visible_places(ocr_lines)) >= 3

    def list_screen(self, ocr_lines):
        texts = [norm(t) for t, _ in ocr_lines]
        p = sum(1 for t in texts if any(whole_line(n, t) for n in self.person_names))
        e = sum(1 for t in texts if any(whole_line(n, t) for n in self.evid_names))
        if p >= 4 and p >= e:
            return '人物'
        if e >= 3:
            return '證據'
        return None


# ------------------------------------------------------------------ ocr worker
class Watcher(threading.Thread):
    """Grabs the game window every `interval` s and posts ('ocr', (rect, lines)),
    ('status', msg) or ('error', msg) to the queue."""

    def __init__(self, out_q, interval=1.0):
        super().__init__(daemon=True)
        self.q, self.interval = out_q, interval
        self.paused = False
        self.stop_flag = False
        self.exclude = None   # screen rect (x, y, w, h) to blank out (our own window)

    def run(self):
        try:
            import ocr
            ocr.engine()
        except Exception as e:
            self.q.put(('error', f'OCR 無法啟動：{e}'))
            return
        last, last_status = None, None
        while not self.stop_flag:
            t0 = time.time()
            if not self.paused:
                status = None
                try:
                    rect = ocr.find_game_window()
                    if not rect:
                        status = '找不到遊戲視窗（要開著遊戲、不能最小化）'
                    else:
                        img = ocr.grab(rect)
                        ex = self.exclude
                        if ex:
                            from PIL import ImageDraw
                            x, y = ex[0] - rect[0], ex[1] - rect[1]
                            ImageDraw.Draw(img).rectangle((x, y, x + ex[2], y + ex[3]), fill=(0, 0, 0))
                        lines = ocr.recognize(img)
                        sig = tuple(t for t, _ in lines)
                        if sig != last:
                            last = sig
                            self.q.put(('ocr', (rect, lines)))
                except Exception as e:
                    status = f'OCR 錯誤：{e}'
                if status != last_status:
                    last_status = status
                    self.q.put(('status', status))
            time.sleep(max(0.1, self.interval - (time.time() - t0)))


# ------------------------------------------------------------------ tracker
class Tracker:
    """Position on the chosen route, driven by OCR frames."""

    BACKLOG_LINES = 5     # this many long text lines on screen = backlog / save screen

    def __init__(self, gd, ending, ptr=0):
        self.gd = gd
        self.set_ending(ending, ptr)

    def set_ending(self, ending, ptr=0):
        self.ending = ending
        e = self.gd.routes['endings'][ending]
        self.steps = e['steps']
        self.title = e['title']
        self.file_steps = defaultdict(list)
        for i, s in enumerate(self.steps):
            for f in s['files_before']:
                self.file_steps[f].append(i)
        for f in e['files_after']:
            self.file_steps[f].append(len(self.steps))
        self.ptr = max(0, min(ptr, len(self.steps)))
        self.offroute = False
        self.pending_deduc = None   # step index of the deduction just answered

    # -- step lookup: forward first, then nearest backward
    def _find(self, pred, ahead):
        n = len(self.steps)
        for i in range(self.ptr, min(n, self.ptr + ahead)):
            if pred(self.steps[i]):
                return i
        for i in range(min(self.ptr, n) - 1, max(-1, self.ptr - 4), -1):
            if pred(self.steps[i]):
                return i
        return None

    def classify(self, rect, lines):
        """-> (kind, step) with kind in select/map/deduc (hint), offselect, or (None, None)."""
        if self.gd.is_map_screen(lines):
            seen = self.gd.visible_places(lines)
            return 'map', self._find(lambda s: s['kind'] == 'map' and norm(s['choice_text']) in seen
                                     and sum(norm(o) in seen for o in s['options']) * 2 >= len(s['options']), 4)
        sids = set(self.gd.match_select(lines))
        if sids:
            i = self._find(lambda s: s['kind'] == 'select' and s['id'] in sids, len(self.steps))
            if i is None:   # earlier on the route (an old save was loaded)?
                cands = [k for k, s in enumerate(self.steps) if s['kind'] == 'select' and s['id'] in sids]
                i = min(cands, key=lambda k: abs(k - self.ptr)) if cands else None
            if i is None:
                self.offroute = True
                return 'offselect', None
            self.offroute = False
            return 'select', i
        lst = self.gd.list_screen(lines)
        if lst:
            i = self._find(lambda s: s['kind'] in ('deduc', 'deduc3') and s['list'] == lst, 4)
            if i is not None:
                return 'deduc', i
        self.track_dialog(rect, lines)
        return None, None

    def leave(self, kind, i):
        """The hinted screen disappeared: the choice was made."""
        if i is None:
            return
        self.ptr = max(self.ptr, i + 1)
        self.pending_deduc = i if kind == 'deduc' and self.steps[i]['kind'] == 'deduc' else None

    def track_dialog(self, rect, lines):
        long_lines = [t for t, _ in lines if len(norm(t)) >= 6]
        if len(long_lines) >= self.BACKLOG_LINES:
            return                      # backlog / save-load screen: old text, ignore
        h = rect[3]
        bottom = [t for t, bb in lines if bb[1] > h * 0.55]
        if not bottom:
            return
        cands = []
        for c in [''.join(bottom)] + sorted(bottom, key=len, reverse=True)[:2]:
            cands += self.gd.match_line(c)
        if not cands:
            return
        # deduction retry: the "wrong answer" reaction of the deduction we just left
        pd = self.pending_deduc
        if pd is not None:
            s = self.steps[pd]
            if any(f == s['file'] and b == s.get('wrong_block') for f, b, _ in cands):
                self.ptr = pd
                self.pending_deduc = None
                return
            if any(f == s['file'] and b == s.get('right_block') for f, b, _ in cands):
                self.pending_deduc = None
        best = None
        for f, b, sc in cands:
            idxs = self.file_steps.get(f)
            if not idxs:
                continue
            fwd = [i for i in idxs if i >= self.ptr]
            i = fwd[0] if fwd else idxs[-1]
            key = (abs(i - self.ptr), -sc)
            if best is None or key < best[0]:
                best = (key, i)
        if best is None:
            if all(not f.startswith(('map', 'note')) for f, _, _ in cands):
                self.offroute = True
            return
        self.offroute = False
        self.ptr = best[1]


def default_ending(gd, want):
    e = gd.routes['endings']
    if want in e:
        return want
    return '11' if '11' in e else sorted(e, key=int)[-1]


def alternatives(gd, s):
    """[(option text, [ending numbers])] for the other choices at this step."""
    pts = gd.routes['points'].get(s.get('pid', s['id']), {})
    return [(v['text'], sorted({int(x) for x in v['endings']}))
            for k, v in pts.items() if k != str(s['choice'])]


def hint_text(gd, tracker, i):
    s = tracker.steps[i]
    if s['kind'] == 'select':
        main = f'選第 {s["choice"] + 1} 個：{s["choice_text"]}'
    elif s['kind'] == 'map':
        main = f'去「{s["choice_text"]}」'
    elif s['kind'] == 'deduc':
        main = f'選「{s["choice_text"]}」'
    else:
        main = f'選：{s["choice_text"]}'
    sub = []
    aff = [e for e in s.get('effects', []) if '好感' in e]
    if aff:
        sub.append('、'.join(aff))
    others = [f'「{t}」→結局{",".join(map(str, ends))}' for t, ends in alternatives(gd, s)]
    if others:
        sub.append('其他：' + '；'.join(others[:2]))
    if s['kind'] == 'deduc':
        sub.append('答錯只會重來')
    return main, '\n'.join(sub)
