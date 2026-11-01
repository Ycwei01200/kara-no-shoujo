import sys, os, pickle, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sim
sim.ABSTRACT.update(str(n) for n in range(100, 111))
W = sim.World()
live = sim.compute_liveness(W)
t = time.time()
parent, ends, ev = sim.explore(W, '00a_0000_0000', max_states=5_000_000, live=live)
print('states', len(parent), 'time', round(time.time()-t), 'ends', sorted(ends))
for k, v in ev.items(): print(k, len(v), sorted(v)[:4])
res = {}
for n, (node, pos, st) in sorted(ends.items()):
    res[n] = {'path': sim.path_to(parent, node), 'endpos': pos}
pickle.dump(res, open(os.path.join(os.path.dirname(__file__), '..', 'data', 'abstract_paths.pkl'), 'wb'))
for n, r in res.items():
    d = r['path']
    print(n, 'decisions', len(d), 'assumes', [x[3:] for x in d if x and x[0]=='assume'][:12])
