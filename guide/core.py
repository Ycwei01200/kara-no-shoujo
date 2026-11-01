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

ACT_RE = re.compile(r'\[\s*(act\d+)\s*\]', re.I)
PUNCT = re.compile(r'[\s　「」『』（）()、，,。．.…‥・·•！!？?：:；;“”"‘’\'\-—―～~〈〉《》【】\[\]]+')


def norm(s):
    return PUNCT.sub('', s)


def whole_line(name, t):
    """OCR line t is (almost) exactly the label `name`."""
    return t == name or (name in t and len(t) <= len(name) + 2)


SEARCH_MARKS = ('結束調查', '進行調查', '結束調', '進行調')       # buttons of the investigation screen
HINTS = os.path.join(DATA, 'hints')
MAP_MARKS = ('選擇要去的場所', '擇要去的場所', '要去的場所')     # header of the map screen
DEDUC_MARK = '進行推理'                                  # shown only while a deduction is open
NOTEBOOK_MARKS = ('回顧歷史訊息', '回歷史訊息', '手帳')
SETTINGS_MARKS = ('進行配置設定', '進行置設定', '配置設定')      # config screen opened over the game
LIST_NO = re.compile(r'^[A-Za-z0-9]{1,4}')


def marked(texts, marks, slack=3):
    """Some OCR line is (about) one of the UI labels `marks`, not a dialogue line containing it."""
    return any(m in t and len(t) <= len(m) + slack for t in texts for m in marks)


def fuzzy_line(name, t):
    """Like whole_line, but allows OCR misreads in longer labels ('多磿陵園' for '多磨陵園')."""
    if whole_line(name, t):
        return True
    t = LIST_NO.sub('', t)          # list numbers glued to the name ('D02', '82')
    if whole_line(name, t):
        return True
    if len(name) < 4 or abs(len(t) - len(name)) > 3:
        return False
    return difflib.SequenceMatcher(None, name, t).ratio() >= 0.7


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
        p = sum(1 for t in texts if any(fuzzy_line(n, t) for n in self.person_names))
        e = sum(1 for t in texts if any(fuzzy_line(n, t) for n in self.evid_names))
        if p >= 4 and p >= e:
            return '人物'
        if e >= 3:
            return '證據'
        return None


# ------------------------------------------------------------------ ocr worker
class _Skip(Exception):
    pass


class Watcher(threading.Thread):
    """Grabs the game window every `interval` s and posts ('ocr', (rect, lines)),
    ('status', msg) or ('error', msg) to the queue."""

    def __init__(self, out_q, interval=1.0):
        super().__init__(daemon=True)
        self.q, self.interval = out_q, interval
        self.paused = False
        self.stop_flag = False
        self.exclude = []     # screen rects (x, y, w, h) to blank out (our own windows)

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
                    found = ocr.find_game_window(with_title=True)
                    rect, title = found if found else (None, '')
                    if not rect:
                        status = '找不到遊戲視窗（要開著遊戲、不能最小化）'
                    else:
                        if not ocr.is_unobscured():
                            # (forcing the game to repaint for a capture makes it flicker, so wait)
                            status = '遊戲視窗被其他視窗蓋住，切回遊戲就會繼續偵測'
                            raise _Skip
                        img = ocr.grab(rect)
                        if self.exclude:
                            from PIL import ImageDraw
                            dr = ImageDraw.Draw(img)
                            for ex in list(self.exclude):
                                x, y = ex[0] - rect[0], ex[1] - rect[1]
                                dr.rectangle((x, y, x + ex[2], y + ex[3]), fill=(0, 0, 0))
                        lines = ocr.recognize(img)
                        sig = (title, tuple(t for t, _ in lines))
                        if sig != last:
                            last = sig
                            self.q.put(('ocr', (rect, lines, title)))
                except _Skip:
                    pass
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
        # every deduction in the game: its question / wrong-answer blocks -> entry
        self.ded_by_block = defaultdict(list)
        for e in gd.routes.get('deductions', []):
            for b in e['ask_blocks']:
                self.ded_by_block[(e['file'], b)].append((e, 'ask'))
            self.ded_by_block[(e['file'], e['block'])].append((e, 'wrong'))
        self.cur_deduc = None       # the deduction whose question/retry text was seen last
        self.last_file = None
        self.set_ending(ending, ptr)

    def set_ending(self, ending, ptr=0):
        self.ending = ending
        e = self.gd.routes['endings'][ending]
        self.steps = e['steps']
        self.title = e['title']
        self.acts = e.get('acts', {})
        # blocks shown right before a deduction opens (its question) -> step
        self.deduc_blocks = defaultdict(list)
        for i, s in enumerate(self.steps):
            for b in s.get('ask_blocks', []):
                self.deduc_blocks[(s['file'], b)].append(i)
        self.file_steps = defaultdict(list)
        for i, s in enumerate(self.steps):
            for f in s['files_before']:
                self.file_steps[f].append(i)
        for f in e['files_after']:
            self.file_steps[f].append(len(self.steps))
        self.ptr = max(0, min(ptr, len(self.steps)))
        self.offroute = False
        self.pending_deduc = None   # step index of the deduction just answered
        self.act = None             # chapter from the game's window title
        self.synced_act = None
        self.in_deduction = False   # saw '進行推理' and no normal dialogue since
        self.cur_deduc = None

    # -- step lookup: forward first, then nearest backward
    def _find(self, pred, ahead, act=False):
        n = len(self.steps)
        ok = (lambda i: pred(self.steps[i]) and self._in_act(i)) if act else (lambda i: pred(self.steps[i]))
        for i in range(self.ptr, min(n, self.ptr + ahead)):
            if ok(i):
                return i
        for i in range(min(self.ptr, n) - 1, max(-1, self.ptr - 4), -1):
            if ok(i):
                return i
        return None

    def act_range(self, act):
        """Steps that can be reached while the title shows `act` (inclusive)."""
        acts = self.acts
        if act not in acts:
            return None
        n = int(act[3:])
        later = [v for k, v in acts.items() if int(k[3:]) > n]
        return acts[act], (min(later) if later else len(self.steps))

    def sync_title(self, title):
        """Window title shows the chapter ('[ act24 ]'): keep ptr inside it."""
        m = ACT_RE.search(title or '')
        self.act = m.group(1).lower() if m else None
        if not self.act or self.act == self.synced_act:
            return
        r = self.act_range(self.act)
        if r is None:
            return
        self.synced_act = self.act
        if not (r[0] <= self.ptr <= r[1]):
            self.ptr = r[0]
            self.pending_deduc = None

    def _in_act(self, i):
        r = self.act_range(self.act) if self.act else None
        return r is None or r[0] <= i <= r[1]

    def _next_is_deduction(self):
        """The next route decision (searches skipped) is a deduction in this chapter."""
        for i in range(self.ptr, len(self.steps)):
            if self.steps[i]['kind'] != 'search':
                return self.steps[i]['kind'] in ('deduc', 'deduc3') and self._in_act(i)
        return False

    def classify(self, rect, lines, title=''):
        """-> (kind, step) with kind in select/map/deduc (hint), offselect, or (None, None)."""
        self.sync_title(title)
        texts = [norm(t) for t, _ in lines]
        if marked(texts, SEARCH_MARKS):
            return 'search', self._find(lambda s: s['kind'] == 'search', 4, act=True)
        if marked(texts, MAP_MARKS):
            # place labels may not be readable; the route's next map move in this chapter
            return 'map', self._find(lambda s: s['kind'] == 'map', 4, act=True)
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
        if marked(texts, SETTINGS_MARKS):
            return 'hold', None                     # config screen: keep whatever is shown
        if marked(texts, (DEDUC_MARK,)):
            self.in_deduction = True
        notebook = marked(texts, NOTEBOOK_MARKS, 2) or any('人物名單' in t and '筆記' in t for t in texts)
        if notebook and self.cur_deduc:
            e = self.cur_deduc
            ids = (f"deduc:{e['file']}:{e['block']}", f"deduc3:{e['file']}:{e['block']}")
            for i, s in enumerate(self.steps):
                if s['id'] in ids:
                    return 'deduc', i
            return 'deduc_x', e                     # not on the target route: still must be answered
        lst_now = self.gd.list_screen(lines) if notebook else None
        if notebook and (self.in_deduction or self._next_is_deduction()):
            # names in the person list are vertical and unreadable; the chapter's next deduction it is
            i = self._find(lambda s: s['kind'] in ('deduc', 'deduc3')
                           and (lst_now is None or s['list'] == lst_now), 6, act=True)
            if i is not None:
                return 'deduc', i
            return 'hold', None
        lst = self.gd.list_screen(lines)
        if lst:
            # the deduction screen and the notebook look the same; only hint a deduction of this chapter
            i = self._find(lambda s: s['kind'] in ('deduc', 'deduc3') and s['list'] == lst, 4, act=True)
            if i is not None:
                return 'deduc', i
        return None, ('dialog' if self.track_dialog(rect, lines) else None)

    def leave(self, kind, i):
        """The hinted screen disappeared: the choice was made."""
        if i is None:
            return
        self.ptr = max(self.ptr, i + 1)
        self.pending_deduc = i if kind == 'deduc' and self.steps[i]['kind'] == 'deduc' else None

    def track_dialog(self, rect, lines):
        """Follow the story by dialogue. True if a script line was recognised."""
        long_lines = [t for t, _ in lines if len(norm(t)) >= 6]
        if len(long_lines) >= self.BACKLOG_LINES:
            return False                # backlog / save-load screen: old text, ignore
        h = rect[3]
        bottom = [t for t, bb in lines if bb[1] > h * 0.55]
        if not bottom:
            return False
        cands = []
        for c in [''.join(bottom)] + sorted(bottom, key=len, reverse=True)[:2]:
            cands += self.gd.match_line(c)
        if not cands:
            return False
        self._follow(cands)
        return True

    def _follow(self, cands):
        self.in_deduction = False       # back to normal dialogue
        # leaving an investigation: its exit script is '<search file>z'
        cur = self.steps[self.ptr] if self.ptr < len(self.steps) else None
        if cur and cur['kind'] == 'search' and any(f.endswith('z') and 'search:' + f[:-1] == cur['id']
                                                   for f, _, _ in cands):
            self.ptr += 1
        files = {f for f, _, _ in cands}
        if len(files) == 1:
            self.last_file = next(iter(files))      # an unambiguous line tells the current scene
        hits = [(e, why) for f, b, _ in cands for e, why in self.ded_by_block.get((f, b), [])]
        if len({e['file'] for e, _ in hits}) > 1:   # generic line ('我翻開筆記本。'): keep this scene's
            hits = [(e, why) for e, why in hits if e['file'] == self.last_file]
        if hits:
            asks = [e for e, why in hits if why == 'ask']
            pool = asks or [e for e, _ in hits]
            if self.cur_deduc in pool:
                pass                    # e.g. the shared '不──不對。' of a retry
            else:
                self.cur_deduc = min(pool, key=lambda e: e['block'])
        else:
            self.cur_deduc = None
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
        # the question text of a deduction pins down exactly which one is coming
        dq = [i for f, b, _ in cands for i in self.deduc_blocks.get((f, b), []) if self._in_act(i)]
        if dq:
            self.ptr = min(dq, key=lambda i: (abs(i - self.ptr), i))
            self.offroute = False
            return
        best = None
        for f, b, sc in cands:
            idxs = [i for i in self.file_steps.get(f, []) if self._in_act(i)]
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


def deduc_x_text(e):
    ans = e['answers']
    labels = {a['label'] for a in ans}
    if len(ans) == 1:
        main = f'選「{ans[0]["text"]}」'
    else:
        main = '可選：' + '／'.join(a['text'] for a in ans)
    sub = '這題不在目標路線上（你走的路線和目標不同），但要答對才能繼續。'
    if len(labels) > 1:
        sub += '\n不同答案會走向不同劇情。'
    return main, sub


def hint_text(gd, tracker, i):
    s = tracker.steps[i]
    if s['kind'] == 'select':
        main = f'選第 {s["choice"] + 1} 個：{s["choice_text"]}'
    elif s['kind'] == 'map':
        main = f'去「{s["choice_text"]}」'
    elif s['kind'] == 'deduc':
        main = f'選「{s["choice_text"]}」'
    elif s['kind'] == 'search':
        n = sum(1 for c in s['clicks'] if c not in (0, 'R'))
        main = f'搜查：照圖上的數字點 {n} 下'
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
    if s['kind'] == 'search':
        sub.append('同一處標「5·7」= 第 5、第 7 下都點這裡')
        if 'Z' in s['clicks']:
            sub.append('有兩張圖時：左圖點完會放大成右圖，右圖點完按「返回」')
        sub.append('點完再按「結束調查」')
    return main, '\n'.join(sub)
