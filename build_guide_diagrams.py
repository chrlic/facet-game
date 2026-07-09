import sys, json
sys.path.insert(0, '/Users/mdivis/Documents/playground/games')
sys.path.insert(0, '.')
from gen_guide_diagrams import diagram
from backbone_engine import neighbors, jump_targets, SYM_CITIES, START

D = {}

# 1. Board overview — full 9x9, real symmetric city layout + start corners
cells = []
for y in range(9):
    for x in range(9):
        c = {'x': x, 'y': y}
        if (x, y) in SYM_CITIES:
            c['city'] = True
        if (x, y) == START[0]:
            c.update(kind='router', owner=0, startMark=0)
        elif (x, y) == START[1]:
            c.update(kind='router', owner=1, startMark=1)
        cells.append(c)
D['board_overview'] = diagram(cells, pad=20)

# 2. Adjacency — a hex and its 6 neighbors
cx, cy = 4, 3
nbrs = neighbors(cx, cy)
cells = [{'x': cx, 'y': cy, 'kind': 'router', 'owner': 0, 'label': 'this hex'}]
for i, (nx, ny) in enumerate(nbrs):
    cells.append({'x': nx, 'y': ny, 'city': False})
edges = [((cx, cy), (nx, ny), 'link') for (nx, ny) in nbrs]
D['adjacency'] = diagram(cells, edges)

# 3. Wireless AP jump
ax, ay = 3, 3
mid, far = jump_targets(ax, ay)[2]  # pick one direction
cells = [
    {'x': ax, 'y': ay, 'kind': 'ap', 'owner': 0, 'label': 'Wireless AP'},
    {'x': mid[0], 'y': mid[1], 'label': 'jumped (not owned)'},
    {'x': far[0], 'y': far[1], 'kind': 'router', 'owner': 0, 'label': 'connected!'},
]
D['ap_jump'] = diagram(cells, [((ax, ay), far, 'jump')])

# 4. Router expansion (before / after)
before = [
    {'x': 2, 'y': 2, 'kind': 'router', 'owner': 0},
    {'x': 3, 'y': 2, 'kind': 'router', 'owner': 0},
    {'x': 4, 'y': 2},
]
D['router_before'] = diagram(before, [((2, 2), (3, 2), 'link')])
after = [
    {'x': 2, 'y': 2, 'kind': 'router', 'owner': 0},
    {'x': 3, 'y': 2, 'kind': 'router', 'owner': 0},
    {'x': 4, 'y': 2, 'kind': 'router', 'owner': 0, 'label': 'new'},
]
D['router_after'] = diagram(after, [((2, 2), (3, 2), 'link'), ((3, 2), (4, 2), 'link')])

# 5. Switch placement: valid (2 neighbors) vs invalid (1 neighbor)
valid = [
    {'x': 2, 'y': 2, 'kind': 'router', 'owner': 0},
    {'x': 3, 'y': 3, 'kind': 'router', 'owner': 0},
    {'x': 2, 'y': 3, 'kind': 'switch', 'owner': 0, 'label': 'OK — touches 2'},
]
D['switch_valid'] = diagram(valid, [((2, 2), (2, 3), 'link'), ((3, 3), (2, 3), 'link')])
invalid = [
    {'x': 2, 'y': 2, 'kind': 'router', 'owner': 0},
    {'x': 4, 'y': 2},
    {'x': 3, 'y': 2, 'kind': 'switch', 'owner': 0, 'disconnected': True,
     'label': 'illegal — touches 1'},
]
D['switch_invalid'] = diagram(invalid, [((2, 2), (3, 2), 'link')])

# 6. Hack cutting the network — before / after
netbefore = [
    {'x': 2, 'y': 2, 'kind': 'router', 'owner': 0, 'label': 'START'},
    {'x': 3, 'y': 2, 'kind': 'router', 'owner': 0, 'label': 'bridge'},
    {'x': 4, 'y': 2, 'kind': 'dc', 'owner': 0, 'dcOnline': None, 'label': 'Datacenter'},
]
D['hack_before'] = diagram(netbefore, [((2, 2), (3, 2), 'link'), ((3, 2), (4, 2), 'link')])
netafter = [
    {'x': 2, 'y': 2, 'kind': 'router', 'owner': 0},
    {'x': 3, 'y': 2, 'kind': 'router', 'owner': 0, 'disabled': True, 'label': 'HACKED'},
    {'x': 4, 'y': 2, 'kind': 'dc', 'owner': 0, 'dcOnline': None, 'disconnected': True,
     'label': 'cut off!'},
]
D['hack_after'] = diagram(netafter, [((2, 2), (3, 2), 'link')])

# 7. Firewall absorbs a hack
fw = [
    {'x': 3, 'y': 3, 'kind': 'server', 'owner': 0, 'fw': True, 'label': 'Firewall holds'},
]
D['firewall'] = diagram(fw)

# 8. Server connects a City
srv = [
    {'x': 4, 'y': 4, 'city': True, 'cityBy': [0]},
    {'x': 3, 'y': 4, 'kind': 'server', 'owner': 0, 'serverActive': True, 'label': 'Server'},
]
D['server_city'] = diagram(srv, [((4, 4), (3, 4), 'link')])

# 9. Datacenter online vs offline
nbrs33 = neighbors(3, 3)
r1, r2, s1 = nbrs33[0], nbrs33[1], nbrs33[2]
online = [
    {'x': 3, 'y': 3, 'kind': 'dc', 'owner': 0, 'dcOnline': True, 'label': 'online: +1 AI token'},
    {'x': r1[0], 'y': r1[1], 'kind': 'router', 'owner': 0},
    {'x': r2[0], 'y': r2[1], 'kind': 'router', 'owner': 0},
    {'x': s1[0], 'y': s1[1], 'kind': 'server', 'owner': 0, 'label': 'Server'},
]
D['dc_online'] = diagram(online, [((3, 3), r1, 'link'), ((3, 3), r2, 'link'),
                                   ((3, 3), s1, 'link')])
nbrs63 = neighbors(6, 3)
r1b = nbrs63[0]
offline = [
    {'x': 6, 'y': 3, 'kind': 'dc', 'owner': 0, 'dcOnline': False,
     'label': 'offline: needs\n1 more Router'},
    {'x': r1b[0], 'y': r1b[1], 'kind': 'router', 'owner': 0},
]
D['dc_offline'] = diagram(offline, [((6, 3), r1b, 'link')])

# 10. DC link bonus — two online DCs in one network
dc_a = (2, 5); dc_b = (5, 5)
rr = neighbors(*dc_a)[:2]
rr2 = neighbors(*dc_b)[:2]
link = [
    {'x': dc_a[0], 'y': dc_a[1], 'kind': 'dc', 'owner': 0, 'dcOnline': True},
    {'x': rr[0][0], 'y': rr[0][1], 'kind': 'router', 'owner': 0},
    {'x': rr[1][0], 'y': rr[1][1], 'kind': 'router', 'owner': 0},
    {'x': 3, 'y': 5, 'kind': 'router', 'owner': 0},
    {'x': 4, 'y': 5, 'kind': 'server', 'owner': 0},
    {'x': dc_b[0], 'y': dc_b[1], 'kind': 'dc', 'owner': 0, 'dcOnline': True},
    {'x': rr2[0][0], 'y': rr2[0][1], 'kind': 'router', 'owner': 0},
    {'x': rr2[1][0], 'y': rr2[1][1], 'kind': 'router', 'owner': 0},
]
edges = [(dc_a, rr[0], 'link'), (dc_a, rr[1], 'link'),
        (rr[0], (3, 5), 'link'), ((3, 5), (4, 5), 'link'), ((4, 5), dc_b, 'link'),
        (dc_b, rr2[0], 'link'), (dc_b, rr2[1], 'link')]
D['dc_link'] = diagram(link, edges, pad=18)

with open('diagrams.json', 'w') as f:
    json.dump(D, f)
print('generated', len(D), 'diagrams:', list(D.keys()))
for k, v in D.items():
    print(f'  {k}: {len(v)} chars')
