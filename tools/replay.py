"""Replay decision paths with full concrete state; verify each reaches its ending."""
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim  # noqa: E402

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')


def flatten(path):
    out = []
    for d in path:
        if d and d[0] == 'searchrun':
            out.extend(flatten(d[2]))
        else:
            out.append(d)
    return out


def replay(W, path, target, start='00a_0000_0000'):
    pos = W.start_of(start)
    st = sim.mkstate({}, (), {}, None, {})
    decs = flatten(path)
    k = 0
    enter = False
    while True:
        nxt = None
        for dec, np, ns, ev in sim.successors(W, pos, st, enter_search=enter):
            if ev is not None:
                if ev[0] == 'END':
                    if ev[1] == target:
                        return ev[1], k, len(decs), ns
                    continue
                if ev[0] == 'SEARCH':
                    pos, st = ev[1], ev[2]
                    nxt = 'search'
                    break
                return ('EVENT', ev[0]), k, len(decs), st
            if k < len(decs) and dec == decs[k]:
                nxt = (np, ns)
                break
        if nxt == 'search':
            enter = True
            continue
        enter = False
        if nxt is None:
            return ('NOMATCH', decs[k] if k < len(decs) else None), k, len(decs), st
        pos, st = nxt
        k += 1


def main():
    W = sim.World()
    conc = pickle.load(open(os.path.join(DATA, 'concrete_paths.pkl'), 'rb'))
    mx = pickle.load(open(os.path.join(DATA, 'max_106.pkl'), 'rb'))
    routes = {n: conc[n]['path'] for n in conc}
    for n in (12, 13, 14):
        routes[n] = mx[n]['path']
    ok = {}
    for n, p in sorted(routes.items()):
        r, k, tot, st = replay(W, p, n)
        good = r == n and k == tot
        ok[n] = good
        print(n, 'OK' if good else 'FAIL', r, f'{k}/{tot}', {a: b for a, b in st[0] if a.startswith('1')})
    pickle.dump({n: flatten(p) for n, p in routes.items() if ok[n]},
                open(os.path.join(DATA, 'routes_verified.pkl'), 'wb'))
    bad = [n for n in ok if not ok[n]]
    if bad:
        sys.exit(f'replay failed for endings {bad}')


if __name__ == '__main__':
    main()
