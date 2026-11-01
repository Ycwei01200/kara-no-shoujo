import sys, os, pickle, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim
W = sim.World()
live = sim.compute_liveness(W)
t = time.time()
parent, ends, ev = sim.explore(W, '00a_0000_0000', max_states=5_000_000, live=live,
                               payload=frozenset(str(n) for n in range(100, 111)))
print('states', len(parent), 'time', round(time.time()-t), 'ends', sorted(ends))
res = {n: {'path': sim.path_to(parent, node), 'endpos': pos, 'final': st}
       for n, (node, pos, st) in sorted(ends.items())}
pickle.dump(res, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'concrete_paths.pkl'), 'wb'))
for n, r in res.items():
    print(n, len(r['path']), r['endpos'][0])
