"""Exhaustive flow simulator for The Shell Part I scripts.

Explores every choice (dialogue select / map place / investigation hotspot /
deduction answer) with BFS over (position, game-state), and records the first
(shortest) decision path that reaches each ending flag g.endNN.
"""
import glob
import itertools
import os
import pickle
import re
import sys
from collections import deque

sys.path.insert(0, os.path.dirname(__file__))
import ast_parser as A  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), '..', 'data')
SCRIPT = os.path.join(ROOT, 'script')


def load_all():
    files = {}
    for p in glob.glob(os.path.join(SCRIPT, '*.ast')):
        name = os.path.basename(p)[:-4]
        d = A.load(p).get('ast')
        if d is not None:
            files[name] = d
    return files


def load_tables():
    tb = A.load(os.path.join(ROOT, 'img', 'pc', 'tw', 'game', 'map', 'map.ipt'))
    maps = {k: list(v.arr) for k, v in tb['map'].map.items()}
    src = open((os.path.join(ROOT, 'system', 'list_windows.tbl') if os.path.exists(os.path.join(ROOT, 'system', 'list_windows.tbl')) else os.path.join(ROOT, 'system', 'table', 'list_windows.tbl')), encoding='utf-8-sig').read()
    inve = {}
    for m in re.finditer(r'^no(\d\d)=\{"([^"]+)",(\d+),"[^"]*"(?:,"[^"]*")?((?:,\d+)*)\}', src, re.M):
        inve[int(m.group(1))] = (m.group(2), int(m.group(3)),
                                 [int(x) for x in m.group(4).split(',') if x])
    return maps, inve


class World:
    def __init__(self):
        self.files = load_all()
        self.maps, self.inve = load_tables()
        # file -> investigation base file (for `search` without no)
        sel = A.load(os.path.join(ROOT, 'img', 'pc', 'tw', 'game', 'note', 'notesel.ipt'))['note']
        NOTE_KIND.update({k: v for k, v in sel.map.items() if isinstance(k, int)})
        for d in self.files.values():
            for b, blk in d.map.items():
                if b == 'label':
                    continue
                cur = None
                for x in blk.arr:
                    if x.arr[0] == 'user' and x.map.get('mode') == 'deductive':
                        cur = x.map.get('no')
                    elif x.arr[0] == 'user' and x.map.get('mode') == 'deduc_chk' and cur is not None:
                        RELEVANT.add(('P' if NOTE_KIND.get(cur, 1) == 1 else 'E') + str(x.map['no']))
        RELEVANT.update('P%d' % c for c in HANDWRITING)
        self.search_base = {}
        for no, (fl, mx, zoom) in self.inve.items():
            for suf in ('', 's', 'z'):
                self.search_base[fl + suf] = fl

    def blocks(self, f):
        return self.files[f]

    def start_of(self, f, label=None):
        d = self.files.get(f)
        if d is None:
            return None
        lt = d.get('label')
        if label is None:
            label = 'top'
        if lt is not None and label in lt:
            e = lt[label]
            return (f, e['block'], e['label'] - 1)
        if label == 'top':
            for k in d.map:
                if k != 'label':
                    return (f, k, 0)
        return None

    def cmd(self, pos):
        f, b, i = pos
        blk = self.files[f].get(b)
        if blk is None:
            return None, None
        if i < len(blk.arr):
            return blk.arr[i], blk
        return 'EOB', blk


# ---------------------------------------------------------------- state
# state: tuple(sorted(flags.items())) , mapread, mapcheck, inve, blk
def mkstate(flags, mapread, mapcheck, inve, blk):
    return (tuple(sorted(flags.items())), mapread, tuple(sorted(mapcheck.items())), inve,
            tuple(sorted(blk.items())))


EVAL_SET = re.compile(r'^f\.s(\d*)=(-?\d+)$')
EVAL_ADD = re.compile(r'^f\.s(\d*)=f\.s\1\+(-?\d+)$')
EVAL_END = re.compile(r'^g\.end(\d+)=1$')
HANDWRITING = {2: '117', 5: '118', 6: '119', 7: '120', 8: '121', 9: '122', 10: '123',
               11: '124', 12: '125', 18: '126', 26: '127', 27: '128', 29: '129'}
NOTE_KIND = {}      # deduction no -> 1 person / 2 evidence (from notesel.ipt)
RELEVANT = set()    # 'P<id>' / 'E<id>' that some deduction can need
ALLOW_WRONG = False  # wrong deduction answers that skip ahead are not used as route steps
ABSTRACT = set()   # counter flags tracked abstractly (cond -> both outcomes)
COND = re.compile(r'^f\.s(\d*)(==|>|<|>=|<=|~=)(-?\d+)$')


def cond_ok(c, flags):
    if c is None:
        return True
    m = COND.match(c)
    if not m:
        if c.startswith('g.'):
            return False  # first playthrough: global flags unset
        raise ValueError(c)
    v = flags.get(m.group(1), 0)
    n = int(m.group(3))
    return {'==': v == n, '>': v > n, '<': v < n, '>=': v >= n, '<=': v <= n, '~=': v != n}[m.group(2)]


def successors(W, pos, st, enter_search=False, region=None, visit=None):
    """Yield (decision or None, newpos, newstate, event) for one step.

    Linear commands are folded: we advance until a branching command."""
    flags = dict(st[0])
    mapread = st[1]
    mapcheck = dict(st[2])
    inve = st[3]
    blk = dict(st[4])
    steps = 0
    while True:
        steps += 1
        if steps > 200000:
            raise RuntimeError('loop at %s' % (pos,))
        if visit is not None and (not visit or visit[-1] != pos[0]):
            visit.append(pos[0])
        if region is not None and pos[0] not in region and not enter_search and not blk.get(-2):
            yield None, None, None, ('EXIT', pos, mkstate(flags, mapread, mapcheck, inve, blk))
            return
        c, block = W.cmd(pos)
        f, b, i = pos
        if c is None:
            yield None, None, None, ('BADBLOCK', pos)
            return
        if c == 'EOB':
            nx = block.get('linknext')
            if nx is None:
                yield None, None, None, ('EOF', f)
                return
            pos = (f, nx, 0)
            continue
        op = c.arr[0]
        m = c.map
        if op == 'タイトル':   # title screen
            yield None, None, None, ('TITLE', f)
            return
        if op == 'eval':
            e = m['exp'].replace(' ', '')
            r = EVAL_SET.match(e) or EVAL_ADD.match(e)
            if r and r.group(1) in ABSTRACT:
                pos = (f, b, i + 1)
                continue
            r = EVAL_SET.match(e)
            if r:
                flags[r.group(1)] = int(r.group(2))
            else:
                r = EVAL_ADD.match(e)
                if r:
                    flags[r.group(1)] = flags.get(r.group(1), 0) + int(r.group(2))
                else:
                    r = EVAL_END.match(e)
                    if r:
                        yield None, None, mkstate(flags, mapread, mapcheck, inve, blk), ('END', int(r.group(1)), pos)
            pos = (f, b, i + 1)
            continue
        if op == 'excall':
            cm = COND.match(m.get('cond') or '')
            if cm and cm.group(1) in ABSTRACT:
                ns = mkstate(flags, mapread, mapcheck, inve, blk)
                if 'file' in m:
                    tp = W.start_of(m['file'], m.get('label'))
                else:
                    tp = W.start_of(f, m.get('label'))
                yield ('assume', f, b, m['cond'], True), tp, ns, None
                yield ('assume', f, b, m['cond'], False), (f, b, i + 1), ns, None
                return
            if not cond_ok(m.get('cond'), flags):
                pos = (f, b, i + 1)
                continue
            if 'file' in m:
                np = W.start_of(m['file'], m.get('label'))
            else:
                lb = m.get('label')
                np = W.start_of(f, lb) or W.start_of(f, 'top')   # engine falls back to top
            if np is None:
                yield None, None, None, ('BADJUMP', pos, dict(m))
                return
            pos = np
            continue
        if op == 'select':
            # gather options in this block
            opts = [x for x in block.arr if x.arr[0] == 'select' and 'label' in x.map]
            name = next((x.map['name'] for x in block.arr if x.arr[0] == 'select' and 'name' in x.map), None)
            texts = block.get('select')
            tw = list(texts['tw'].arr) if texts is not None and 'tw' in texts else []
            ns = mkstate(flags, mapread, mapcheck, inve, blk)
            for k, o in enumerate(opts):
                if not cond_ok(o.map.get('cond'), flags):
                    continue
                np = W.start_of(f, o.map['label'])
                yield ('select', f, b, name, k, tw[k] if k < len(tw) else '?'), np, ns, None
            return
        if op == 'user':
            md = m.get('mode')
            if md == 'map':
                nm, no = m['name'], m['no']
                if no == 0:
                    mapread = ()
                for place in W.maps[nm]:
                    if place in mapread:
                        continue
                    mc = dict(mapcheck)
                    mc[nm] = no
                    ns = mkstate(flags, tuple(sorted(mapread + (place,))), mc, inve, blk)
                    np = W.start_of('%s_%02d' % (nm, place))
                    yield ('map', f, b, nm, no, place), np, ns, None
                return
            if md == 'mapcheck':
                if mapcheck.get(m['name']) == 1 and 'label' in m:
                    pos = W.start_of(f, m['label'])
                else:
                    pos = (f, b, i + 1)
                continue
            if md in ('namechar', 'setproof'):
                k = ('P' if md == 'namechar' else 'E') + str(m['ch'])
                if k in RELEVANT:
                    flags[k] = 1
                pos = (f, b, i + 1)
                continue
            if md == 'setblock':
                if 'P%d' % m['ch'] in RELEVANT:
                    flags['B%d' % m['ch']] = 1
                pos = (f, b, i + 1)
                continue
            if md == 'set_deduc':
                for k in [k for k in flags if k.startswith('B')]:
                    del flags[k]
                pos = (f, b, i + 1)
                continue
            if md == 'search_blk':
                blk[m['no']] = m['count']
                pos = (f, b, i + 1)
                continue
            if md == 'search_chk':
                if blk.get(m['no'], 0) == m['count']:
                    pos = W.start_of(f, m['label'])
                else:
                    pos = (f, b, i + 1)
                continue
            if md == 'search':
                resume = blk.pop(-2, 0) == 1      # back from zoom-in / return: same screen
                if 'no' in m and not enter_search and not resume:
                    yield None, None, None, ('SEARCH', pos, mkstate(flags, mapread, mapcheck, inve, blk))
                    return
                enter_search = False
                if 'no' in m and not resume:
                    inve = m['no']
                    blk = {}
                fl, mx, zoom = W.inve[inve]
                zcheck = set(zoom)            # hotspots only clickable inside the zoom view
                active = blk.get(-1, 0) == 1  # blk[-1] = zoomactive
                for k in range(1, mx + 1):
                    if active != (k in zcheck):
                        continue
                    if k == 1 and zoom and not active:
                        b1 = blk.get(1, 0)
                        if b1 >= 1 and (inve != 4 or b1 == 2):
                            b2 = dict(blk)
                            b2[-1] = 1
                            b2[-2] = 1
                            yield (('search', f, b, inve, 'Z'), (f, b, i),
                                   mkstate(flags, mapread, mapcheck, inve, b2), None)
                            continue
                    np = W.start_of(fl + 's', '%02d' % k)
                    if np:
                        yield ('search', f, b, inve, k), np, mkstate(flags, mapread, mapcheck, inve, blk), None
                if active:
                    b2 = dict(blk)
                    b2.pop(-1, None)
                    b2[-2] = 1
                    yield ('search', f, b, inve, 'R'), (f, b, i), mkstate(flags, mapread, mapcheck, inve, b2), None
                np = W.start_of(fl + 'z')
                if np:
                    b2 = dict(blk)
                    b2.pop(-1, None)
                    yield ('search', f, b, inve, 0), np, mkstate(flags, mapread, mapcheck, inve, b2), None
                return
            if md == 'deductive' and m.get('no') == 4:
                # 筆跡: pick 3 people; each with a handwriting entry sets f.sNNN=1
                blocked = {x.map['ch'] for x in block.arr[:i]
                           if x.arr[0] == 'user' and x.map.get('mode') == 'setblock'}
                cands = [c for c in sorted(HANDWRITING)
                         if c not in blocked and flags.get('P%d' % c) and not flags.get('B%d' % c)]
                for combo in itertools.combinations(cands, 3):
                    fl2 = dict(flags)
                    for c in combo:
                        fl2[HANDWRITING[c]] = 1
                    ns = mkstate(fl2, mapread, mapcheck, inve, blk)
                    yield ('deduc3', f, b, 4, combo), (f, b, i + 1), ns, None
                return
            if md == 'deductive':
                # the answer is compared by following deduc_chk commands
                chks = [x for x in block.arr[i + 1:] if x.arr[0] == 'user' and x.map.get('mode') == 'deduc_chk']
                pre = 'P' if NOTE_KIND.get(m.get('no'), 1) == 1 else 'E'
                vals = [x.map['no'] for x in chks
                        if flags.get(pre + str(x.map['no'])) and not (pre == 'P' and flags.get('B%d' % x.map['no']))]
                if not vals:
                    if not ALLOW_WRONG:   # route must collect the evidence first
                        return
                    vals = [-1]
                for v in vals:
                    fl2 = dict(flags)
                    fl2[''] = v
                    ns = mkstate(fl2, mapread, mapcheck, inve, blk)
                    yield ('deduc', f, b, m.get('no'), v), (f, b, i + 1), ns, None
                return
            if md == 'deduc_chk':
                if flags.get('', None) == m['no']:
                    pos = W.start_of(f, m['label'])
                else:
                    pos = (f, b, i + 1)
                continue
            pos = (f, b, i + 1)
            continue
        pos = (f, b, i + 1)


# ---------------------------------------------------------------- liveness
def _cond_var(c):
    if not c:
        return None
    m = COND.match(c)
    return 'f' + m.group(1) if m else None


def static_edges(W, pos):
    """Return (gen:set, kill:set, succs:list) for the command at pos."""
    c, block = W.cmd(pos)
    f, b, i = pos
    nxt = (f, b, i + 1)
    if c is None:
        return set(), set(), []
    if c == 'EOB':
        nx = block.get('linknext')
        return set(), set(), [(f, nx, 0)] if nx else []
    op, m = c.arr[0], c.map
    gen, kill, succ = set(), set(), [nxt]
    if op == 'タイトル':
        return gen, kill, []
    if op == 'eval':
        e = m['exp'].replace(' ', '')
        r = EVAL_SET.match(e)
        if r:
            kill.add('f' + r.group(1))
        else:
            r = EVAL_ADD.match(e)
            if r:
                gen.add('f' + r.group(1))
            elif EVAL_END.match(e):
                pass
    elif op == 'excall':
        v = _cond_var(m.get('cond'))
        if v:
            gen.add(v)
        if 'file' in m:
            t = W.start_of(m['file'], m.get('label'))
        else:
            t = W.start_of(f, m.get('label')) or W.start_of(f, 'top')
        succ = ([t] if t else []) + ([nxt] if m.get('cond') else [])
    elif op == 'select':
        succ = []
        for x in block.arr:
            if x.arr[0] == 'select' and 'label' in x.map:
                v = _cond_var(x.map.get('cond'))
                if v:
                    gen.add(v)
                t = W.start_of(f, x.map['label'])
                if t:
                    succ.append(t)
    elif op == 'user':
        md = m.get('mode')
        if md == 'map':
            nm = m['name']
            if m['no'] == 0:
                kill.add('MR')
            else:
                gen.add('MR')
            kill.add('MC:' + nm)
            succ = [t for t in (W.start_of('%s_%02d' % (nm, p)) for p in W.maps[nm]) if t]
        elif md == 'mapcheck':
            gen.add('MC:' + m['name'])
            t = W.start_of(f, m['label']) if 'label' in m else None
            succ = [nxt] + ([t] if t else [])
        elif md == 'search_blk':
            gen.add('BLK')  # partial write
        elif md == 'search_chk':
            gen.add('BLK')
            t = W.start_of(f, m['label'])
            succ = [nxt] + ([t] if t else [])
        elif md == 'search':
            if 'no' in m:
                kill.update(('BLK', 'INV'))
                fl, mx, _ = W.inve[m['no']]
            else:
                gen.add('INV')
                fl = W.search_base.get(f)
                mx = 20
            succ = []
            if fl:
                for k in range(1, mx + 1):
                    t = W.start_of(fl + 's', '%02d' % k)
                    if t:
                        succ.append(t)
                t = W.start_of(fl + 'z')
                if t:
                    succ.append(t)
        elif md in ('namechar', 'setproof'):
            k = ('P' if md == 'namechar' else 'E') + str(m['ch'])
            if k in RELEVANT:
                kill.add('f' + k)
        elif md == 'setblock':
            if 'P%d' % m['ch'] in RELEVANT:
                kill.add('fB%d' % m['ch'])
        elif md == 'set_deduc':
            kill.update('fB' + r[1:] for r in RELEVANT if r[0] == 'P')
        elif md == 'deductive':
            kill.add('f')
            gen.update('f' + r for r in RELEVANT)
            gen.update('fB' + r[1:] for r in RELEVANT if r[0] == 'P')
        elif md == 'deduc_chk':
            gen.add('f')
            t = W.start_of(f, m['label'])
            succ = [nxt] + ([t] if t else [])
    return gen, kill, succ


def compute_liveness(W):
    # enumerate all positions
    positions = []
    for f, d in W.files.items():
        for b, blk in d.map.items():
            if b == 'label':
                continue
            for i in range(len(blk.arr) + 1):
                positions.append((f, b, i))
    info = {p: static_edges(W, p) for p in positions}
    preds = {p: [] for p in positions}
    for p, (_, _, ss) in info.items():
        for s in ss:
            if s in preds:
                preds[s].append(p)
    live = {p: frozenset() for p in positions}
    work = deque(positions)
    inq = set(positions)
    while work:
        p = work.popleft()
        inq.discard(p)
        gen, kill, ss = info[p]
        out = set()
        for s in ss:
            out |= live.get(s, frozenset())
        new = frozenset((out - kill) | gen)
        if new != live[p]:
            live[p] = new
            for q in preds[p]:
                if q not in inq:
                    inq.add(q)
                    work.append(q)
    return live


def project(st, lv):
    flags, mapread, mapcheck, inve, blk = st
    flags = tuple((k, v) for k, v in flags if ('f' + k) in lv)
    mapread = mapread if 'MR' in lv else ()
    mapcheck = tuple((k, v) for k, v in mapcheck if ('MC:' + k) in lv)
    inve = inve if 'INV' in lv else None
    blk = blk if 'BLK' in lv else ()
    return (flags, mapread, mapcheck, inve, blk)


def region_vars(W, files):
    vs = set()
    for f in files:
        d = W.files.get(f)
        if not d:
            continue
        for b, blk in d.map.items():
            if b == 'label':
                continue
            for i in range(len(blk.arr)):
                g, k, _ = static_edges(W, (f, b, i))
                vs |= g | k
    return vs


_summary_cache = {}


def search_summary(W, entry_pos, st, live):
    c, _ = W.cmd(entry_pos)
    no = c.map['no']
    base = W.inve[no][0]
    region = {base + 's', base + 'z'}
    rv = _summary_cache.get(('rv', no))
    if rv is None:
        rv = region_vars(W, region) | {'BLK', 'INV'}
        _summary_cache[('rv', no)] = rv
    flags = dict(st[0])
    loc_flags = {k: v for k, v in flags.items() if ('f' + k) in rv}
    key = (entry_pos, tuple(sorted(loc_flags.items())))
    if key not in _summary_cache:
        s0 = mkstate(loc_flags, (), {}, None, {})
        start = (entry_pos, s0)
        par = {start: None}
        q = deque([start])
        exits = {}
        first = True
        while q:
            node = q.popleft()
            pos, cur = node
            for dec, np, ns, ev in successors(W, pos, cur, enter_search=first and pos == entry_pos, region=region):
                if ev is not None:
                    if ev[0] == 'EXIT':
                        ek = (ev[1], ev[2][0])
                        if ek not in exits:
                            exits[ek] = path_to(par, node)
                        continue
                    if ev[0] == 'SEARCH':
                        raise RuntimeError('nested search %s from %s' % (ev[1], pos))
                    continue
                if np[0] not in region:
                    ek = (np, ns[0])
                    if ek not in exits:
                        exits[ek] = path_to(par, node) + [dec]
                    continue
                ns = project(ns, rv)
                k2 = (np, ns)
                if k2 not in par:
                    par[k2] = (node, dec)
                    q.append(k2)
            first = False
        _summary_cache[key] = exits
    out = []
    for (np, lflags), path in _summary_cache[key].items():
        nf = {k: v for k, v in flags.items() if ('f' + k) not in rv}
        nf.update(dict(lflags))
        ns = mkstate(nf, st[1], dict(st[2]), None, {})
        out.append((np, ns, path))
    return out


def explore(W, start_file, max_states=3_000_000, live=None, payload=frozenset(), score=None):
    """BFS. Flags in `payload` are tracked concretely but ignored for state
    merging (first arrival wins), so conditions on them are evaluated with
    real values along each recorded path."""
    if live is None:
        live = compute_liveness(W)

    def strip(ns):
        if not payload:
            return ns
        return (tuple((k, v) for k, v in ns[0] if k not in payload),) + ns[1:]

    s0 = mkstate({}, (), {}, None, {})
    p0 = W.start_of(start_file)
    k0 = (p0, s0)
    parent = {k0: None}
    full = {k0: s0}
    q = deque([k0])
    ends = {}
    events = {}
    import time as _t
    t0 = _t.time()
    nprint = 0

    def push(node, np, ns, dec):
        ns = project(ns, live.get(np, frozenset()))
        key = (np, strip(ns))
        if key in parent:
            if score is None or score(ns) <= score(full[key]):
                return
        parent[key] = (node, dec)
        full[key] = ns
        q.append(key)

    while q:
        node = q.popleft()
        pos = node[0]
        st = full[node]
        if len(parent) >= nprint:
            nprint += 50000
            print(f'[{_t.time()-t0:6.0f}s] states={len(parent)} q={len(q)} at={pos[0]} '
                  f'nflags={len(st[0])} ends={sorted(ends)}', file=sys.stderr, flush=True)
        for dec, np, ns, ev in successors(W, pos, st):
            if ev is not None:
                if ev[0] == 'SEARCH':
                    for np2, ns2, spath in search_summary(W, ev[1], ev[2], live):
                        push(node, np2, ns2, ('searchrun', ev[1][0], spath))
                    continue
                if ev[0] == 'END':
                    n = ev[1]
                    if n not in ends or (score is not None and score(ns) > score(ends[n][2])):
                        ends[n] = (node, ev[2], ns)
                else:
                    events.setdefault(ev[0], set()).add(repr(ev[1:])[:200])
                continue
            push(node, np, ns, dec)
            if len(parent) > max_states:
                print('state cap reached', file=sys.stderr)
                return parent, ends, events
    return parent, ends, events


def path_to(parent, node):
    out = []
    while parent.get(node) is not None:
        node, dec = parent[node]
        out.append(dec)
    return out[::-1]


if __name__ == '__main__':
    import time
    t = time.time()
    W = World()
    print('loaded', len(W.files), 'files', round(time.time() - t, 1), 's')
    parent, ends, events = explore(W, sys.argv[1] if len(sys.argv) > 1 else '00a_0000_0000')
    print('states', len(parent), 'time', round(time.time() - t, 1))
    print('ends', sorted(ends))
    for k, v in events.items():
        print(k, len(v), list(v)[:5])
