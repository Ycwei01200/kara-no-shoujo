"""Concrete search maximising one affection counter. usage: run_max.py 106"""
import sys, os, pickle, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim
tgt = sys.argv[1]
W = sim.World(); live = sim.compute_liveness(W)
t = time.time()
sc = lambda ns: dict(ns[0]).get(tgt, 0)
parent, ends, ev = sim.explore(W, '00a_0000_0000', max_states=5_000_000, live=live,
                               payload=frozenset(str(n) for n in range(100, 111)), score=sc)
print('states', len(parent), 'time', round(time.time()-t), 'ends', sorted(ends))
res = {n: {'path': sim.path_to(parent, node), 'endpos': pos, 'final': st}
       for n, (node, pos, st) in sorted(ends.items())}
pickle.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', f'max_{tgt}.pkl'), 'wb'))
for n, r in res.items():
    print(n, len(r['path']), 'f.s%s=' % tgt, dict(r['final'][0]).get(tgt))
