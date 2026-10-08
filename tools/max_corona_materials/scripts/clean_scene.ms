-- Scene clean-up: the same surface twice. fileIn'd by refinish_sandstone.ms; defines
--   removeCoincident nodes -> #(objects deleted, of them of another material than the one kept); RC_LOG says which
-- which of two coincident objects to keep: the maker's materials (TG...) before named ones before SketchUp's
-- generic ones (as rebuild_parts.ms does)
fn srcRank m = (
	if m == undefined do return 0
	local nm = m.name
	if matchPattern nm pattern:"TG*" then 3
	else if matchPattern nm pattern:"_auto_*" or matchPattern nm pattern:"Material__*" or matchPattern nm pattern:"material__*" then 1
	else 2
)
-- objects that are the same surface at the same place: SketchUp exports a face twice (once per side, or once more
-- in a component), triangulated alike or not, sometimes a hair apart; the two flicker in renders, in two colours when
-- their materials differ. Two objects are one when their boxes agree to RC_TOL mm (a twentieth of a small part's
-- size) and their surfaces to RC_AREA; the lesser of the two is deleted (by its
-- material's name, srcRank, then the less detailed mesh). Parts that only share a box - a dumbbell's embossed number
-- and its face, a cap and its rim - differ in surface and are kept.
global RC_TOL = 0.4
global RC_AREA = 0.02
global RC_LOG = #()
fn rcBetter a b = (
	local ra = srcRank a[1].material; local rb = srcRank b[1].material
	if ra != rb then ra > rb else a[3] >= b[3]
)
fn removeCoincident nodes = (
	RC_LOG = #()
	local items = #()        -- #(node, area, faces)
	for o in nodes where isValidNode o and superclassof o == GeometryClass and canConvertTo o TriMeshGeometry do (
		local tm = try (snapshotAsMesh o) catch undefined
		if tm == undefined do continue
		local nf = tm.numfaces
		local a = 0.0
		for i = 1 to nf do a += meshop.getFaceArea tm i
		delete tm
		if nf > 0 and a > 0 do append items #(o, a, nf)
	)
	fn byMinX a b = if a[1].min.x < b[1].min.x then -1 else if a[1].min.x > b[1].min.x then 1 else 0
	qsort items byMinX
	local gone = #{}
	local drop = #(); local nDiff = 0
	for i = 1 to items.count where not gone[i] do (
		local A = items[i]
		for j = i + 1 to items.count while items[j][1].min.x - A[1].min.x <= RC_TOL do (
			if gone[j] or gone[i] do continue
			local B = items[j]
			local oa = A[1]; local ob = B[1]
			local d = oa.max - oa.min
			local tol = amin RC_TOL (0.05 * (amax #(d.x, d.y, d.z)))   -- (a small part: a twentieth of its size)
			if (abs (oa.min.x - ob.min.x)) > tol or (abs (oa.min.y - ob.min.y)) > tol or (abs (oa.min.z - ob.min.z)) > tol or \
				(abs (oa.max.x - ob.max.x)) > tol or (abs (oa.max.y - ob.max.y)) > tol or (abs (oa.max.z - ob.max.z)) > tol do continue
			if (abs (A[2] - B[2])) > RC_AREA * (amax A[2] B[2]) do continue
			local keepA = rcBetter A B
			local lose = if keepA then j else i
			gone[lose] = true
			append drop items[lose][1]
			local kept = if keepA then oa else ob
			local lost = items[lose][1]
			local mk = if kept.material != undefined then kept.material.name else ""
			local ml = if lost.material != undefined then lost.material.name else ""
			if mk != ml do nDiff += 1
			append RC_LOG (lost.name + " (" + ml + ") on " + kept.name + " (" + mk + ")")
		)
	)
	if drop.count > 0 do delete drop
	#(drop.count, nDiff)
)

-- a screen, a label, a trim or a pad modelled as its own object lying on a panel, in the same plane (SketchUp: the
-- display face over the console's face): the two fight in renders, in ragged patches of both colours. Where an
-- object's faces lie on the faces of a bigger object (the same plane to SR_PLANE_MM, the face's centre on the other's
-- face), they get vertices of their own and are lifted SR_LIFT_MM off it, along its normal (its outside), so they lie
-- on it. Every object with faces on another's (and that other) is noted in LO_CONTACT: smooth_rounds.ms gives it no
-- TurboSmooth, whose subdivided surface would move off the faces it lies on and push through them (a treadmill's
-- bezel through its screen). Run on meshes without modifiers (the face order is the base mesh's). Returns the faces
-- lifted; LO_LOG says where.
global LO_LOG = #()
global LO_CELL = 1000.0         -- the grid the objects are found on (mm)
-- a face's plane as integers: its normal (either way round, to 1/50) and its distance from the origin on two
-- staggered grids (4 eps wide; two faces a hair apart on either side of one grid's edge meet in the other)
fn loPlaneKeys n d eps = (
	if n.x < -1e-6 or (abs n.x <= 1e-6 and (n.y < -1e-6 or (abs n.y <= 1e-6 and n.z < 0))) do (n = -n; d = -d)
	local nk = ((floor (n.x * 50 + 0.5)) as integer + 50) * 10201 + ((floor (n.y * 50 + 0.5)) as integer + 50) * 101 + ((floor (n.z * 50 + 0.5)) as integer + 50)
	local g = d / (4 * eps)
	#(nk, 2 * ((floor g) as integer), 2 * ((floor (g + 0.5)) as integer) + 1)
)
fn loCells mn mx = (
	local out = #()
	for x = (floor (mn.x / LO_CELL)) as integer to (floor (mx.x / LO_CELL)) as integer do
		for y = (floor (mn.y / LO_CELL)) as integer to (floor (mx.y / LO_CELL)) as integer do
			for z = (floor (mn.z / LO_CELL)) as integer to (floor (mx.z / LO_CELL)) as integer do append out (x as string + "," + y as string + "," + z as string)
	out
)
-- lift these faces of A (ta: its snapshot, in world space) SR_LIFT_MM along up[face], on vertices of their own
fn loLift A ta lift up = (
	if classof A.baseObject != Editable_mesh do convertToMesh A
	local bm = A.mesh                 -- (the node's: the base object's .mesh is a copy)
	if bm.numfaces != ta.numfaces do return 0
	local inv = inverse A.objectTransform
	local nv = bm.numverts
	local copyOf = Dictionary #integer
	local extra = #()
	local faces = Dictionary #integer
	for i in lift do (
		local f = getFace ta i
		local nn = #()
		for v in #(f.x as integer, f.y as integer, f.z as integer) do (
			if not hasDictValue copyOf v do (
				append extra (((getVert ta v) + up[i] * SR_LIFT_MM) * inv)
				copyOf[v] = nv + extra.count
			)
			append nn copyOf[v]
		)
		faces[i] = [nn[1], nn[2], nn[3]]
	)
	setNumVerts bm (nv + extra.count) true
	for k = 1 to extra.count do setVert bm (nv + k) extra[k]
	for i in lift do setFace bm i faces[i]
	meshop.deleteIsoVerts bm         -- (the vertices the lifted faces left, unless other faces use them)
	update A
	lift.numberSet
)
fn liftOverlaps nodes = (
	LO_LOG = #()
	LO_CONTACT = Dictionary #integer
	local eps = SR_PLANE_MM
	-- every object: its mesh in world space, its area and its faces by plane: normal -> (distance -> faces)
	local items = #()     -- #(node, area, mesh, planes)
	for o in nodes where isValidNode o and superclassof o == GeometryClass and o.modifiers.count == 0 and canConvertTo o TriMeshGeometry do (
		local tm = try (snapshotAsMesh o) catch undefined
		if tm == undefined do continue
		local ar = 0.0
		local planes = Dictionary #integer
		for i = 1 to tm.numfaces do (
			ar += meshop.getFaceArea tm i
			local n = getFaceNormal tm i
			local k = loPlaneKeys n (dot n (getVert tm (getFace tm i).x)) eps
			if not hasDictValue planes k[1] do planes[k[1]] = Dictionary #integer
			local sub = planes[k[1]]
			for dk in #(k[2], k[3]) do (if hasDictValue sub dk then append sub[dk] i else sub[dk] = #(i))
		)
		if ar > 0 then append items #(o, ar, tm, planes) else delete tm
	)
	-- every object on the grid, in each cell its box covers
	local grid = Dictionary #string
	for k = 1 to items.count do
		for key in loCells items[k][1].min items[k][1].max do
			if hasDictValue grid key then append grid[key] k else grid[key] = #(k)
	-- each pair of objects whose boxes meet, once: the faces of each lying on the other's
	local hits = for k = 1 to items.count collect #{}           -- faces of k lying on another object
	local ups = for k = 1 to items.count collect (Dictionary #integer)
	local onto = for k = 1 to items.count collect 0               -- the object those faces lie on (the last one)
	for ki = 1 to items.count do (
		local I = items[ki][1]
		local imin = I.min - [eps, eps, eps]; local imax = I.max + [eps, eps, eps]
		local seen = #{}
		for key in loCells I.min I.max where hasDictValue grid key do
			for kj in grid[key] where kj > ki and not seen[kj] do (
				seen[kj] = true
				local J = items[kj][1]
				if J.max.x < imin.x or J.max.y < imin.y or J.max.z < imin.z or J.min.x > imax.x or J.min.y > imax.y or J.min.z > imax.z do continue
				local pI = items[ki][4]; local pJ = items[kj][4]
				local ti = items[ki][3]; local tj = items[kj][3]
				local touch = false
				for nk in (if pI.count <= pJ.count then pI.keys else pJ.keys) do (
					if not hasDictValue pI nk or not hasDictValue pJ nk do continue
					local si = pI[nk]; local sj = pJ[nk]
					for dk in (if si.count <= sj.count then si.keys else sj.keys) do (
						if not hasDictValue si dk or not hasDictValue sj dk do continue
						local fi = si[dk]; local fj = sj[dk]
						-- faces of I on faces of J, and of J on I, in this plane
						for pass = 1 to 2 do (
							local ta = if pass == 1 then ti else tj
							local tb = if pass == 1 then tj else ti
							local fa = if pass == 1 then fi else fj
							local fb = if pass == 1 then fj else fi
							local ka = if pass == 1 then ki else kj
							local kb = if pass == 1 then kj else ki
							for i in fa where not hits[ka][i] do (
								local c = meshop.getFaceCenter ta i
								for j in fb while not hits[ka][i] do (
									local nb = getFaceNormal tb j
									local g = getFace tb j
									local p = getVert tb g.x
									if abs (dot nb (c - p)) <= eps and srPointInTri c p (getVert tb g.y) (getVert tb g.z) nb do (
										hits[ka][i] = true; ups[ka][i] = nb; onto[ka] = kb; touch = true
									)
								)
							)
						)
					)
				)
				if touch do (LO_CONTACT[getHandleByAnim I] = true; LO_CONTACT[getHandleByAnim J] = true)
			)
	)
	-- a smaller object lying within a bigger one's box, on its faces: those faces are lifted off it
	local total = 0
	for k = 1 to items.count where hits[k].numberSet > 0 and onto[k] > 0 do (
		local X = items[k][1]; local B = items[onto[k]][1]
		if items[k][2] >= items[onto[k]][2] do continue
		local bmin = B.min - [eps, eps, eps]; local bmax = B.max + [eps, eps, eps]
		if X.min.x < bmin.x or X.min.y < bmin.y or X.min.z < bmin.z or X.max.x > bmax.x or X.max.y > bmax.y or X.max.z > bmax.z do continue
		-- and X's other faces in the planes where it lies on B (a disc on a dumbbell's face lies partly over a groove
		-- in it: lifting only the faces over B would leave steps between them, which render as dark lines)
		local tx = items[k][3]
		local hp = #()           -- #(normal, distance, up) of each plane
		for i in hits[k] do (
			local n = getFaceNormal tx i; local d = dot n (getVert tx (getFace tx i).x)
			local known = false
			for h in hp while not known do known = (dot n h[1]) > 0.999 and abs (d - h[2]) <= eps
			if not known do append hp #(n, d, ups[k][i])
		)
		for i = 1 to tx.numfaces where not hits[k][i] do (
			local n = getFaceNormal tx i; local d = dot n (getVert tx (getFace tx i).x)
			for h in hp while not hits[k][i] do (
				local c = dot n h[1]
				if (c > 0.999 and abs (d - h[2]) <= eps) or (c < -0.999 and abs (d + h[2]) <= eps) do (hits[k][i] = true; ups[k][i] = h[3])
			)
		)
		local nl = loLift X items[k][3] hits[k] ups[k]
		if nl > 0 do (total += nl; append LO_LOG (X.name + " (" + nl as string + " faces) on " + B.name))
	)
	for it in items do delete it[3]
	total
)
