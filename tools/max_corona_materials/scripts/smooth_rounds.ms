-- Smoother round parts: SketchUp exports curves as a few flat facets, often with every triangle's corners unwelded, so
-- even smoothing groups cannot blend them (a roller shows its facets, its end a polygon). fileIn'd by
-- refinish_sandstone.ms; defines
--   smoothRounds nodes angleDeg iters renderIters -> #(meshes made smooth, objects subdivided, faces before, faces after)
--                                                    (and SR_DUP_FACES: the duplicate faces deleted, SR_LIFTED:
--                                                    the faces of screens and labels lifted off their panel)
-- Every mesh's vertices are welded (SR_WELD_MM, real mm: SketchUp leaves its corners up to half a millimetre apart,
-- and the seams show as lines) and its smoothing groups set again by angle (edges sharper than
-- angleDeg stay hard). A round object - mostly curved surfaces (SR_ROUND_SHARE of its area) - then gets a TurboSmooth that keeps the hard edges
-- and the material borders sharp (separate by smoothing groups and materials): iters in the viewport, renderIters in
-- renders. Flat objects (boxes, plates) keep their faces: subdividing them would add nothing.
-- Instances (SketchUp components) share their mesh: it is welded and smoothed once, for all of them. An object with
-- modifiers (an Edit Poly someone added) is collapsed first, which keeps what the modifiers did.
global SR_WELD_MM = 0.5
-- the weld of one object: SR_WELD_MM, at most a tenth of its smallest dimension (a thin sheet keeps its two sides),
-- in the mesh's own units (sc: the object's scale)
fn srWeldDist o sc = (local d = o.max - o.min; (amin SR_WELD_MM (0.1 * (amin #(d.x, d.y, d.z)))) / sc)
global SR_SKIPPED = #()        -- objects that could not be smoothed (names), for the log

fn srAll n = if n > 0 then #{1..n} else #{}

-- how much of the mesh's area is curved: faces that meet a neighbour smoothly (a shared smoothing group) at more than
-- 8 degrees. A roller, a tube, a handle, a disc's rim are mostly curved; a pad, a plate or a frame mostly flat with
-- rounded edges (subdividing those only ripples their flat faces). Neighbours come from a vertex -> faces table made
-- once per mesh (asking the mesh for every edge's neighbour is far slower).
global SR_ROUND_SHARE = 0.35
fn srCurvedShare tm = (
	local n = tm.numfaces
	if n == 0 do return 0.0
	local fv = for i = 1 to n collect (getFace tm i)
	local vf = for v = 1 to tm.numverts collect #()
	for i = 1 to n do (local f = fv[i]; append vf[f.x as integer] i; append vf[f.y as integer] i; append vf[f.z as integer] i)
	local cosLimit = cos 8.0
	local stepF = amax 1 (n / 2000)   -- a sample is enough on big meshes
	local total = 0.0; local curved = 0.0
	for i = 1 to n by stepF do (
		local a = meshop.getFaceArea tm i
		total += a
		local gi = getFaceSmoothGroup tm i
		if gi == 0 do continue
		local ni = getFaceNormal tm i
		local f = fv[i]
		local ends = #(#(f.x, f.y), #(f.y, f.z), #(f.z, f.x))
		local isCurved = false
		for e in ends while not isCurved do (
			local others = vf[e[2] as integer]
			for j in vf[e[1] as integer] while not isCurved where j != i and (findItem others j) > 0 do
				if (bit.and gi (getFaceSmoothGroup tm j)) != 0 and (dot ni (getFaceNormal tm j)) < cosLimit do isCurved = true
		)
		if isCurved do curved += a
	)
	if total > 0 then curved / total else 0.0
)

-- a dense mesh that is already welded (fewer vertices than faces) and has smoothing groups of its own was modelled
-- with care (Technogym's own Artis machines): it is smooth already and left as it is. A dense mesh with every face in
-- one smoothing group is not: its hard edges are smoothed over, which smears a flat face's shading into blotches and
-- stars (the treadmills' screens and consoles); it is smoothed by angle like the others.
global SR_DENSE_FACES = 20000
fn srOneGroup tm = (
	local n = tm.numfaces
	if n == 0 do return true
	local g = getFaceSmoothGroup tm 1
	local same = true
	for i = 2 to n by (amax 1 (n / 5000)) while same do same = getFaceSmoothGroup tm i == g
	same
)
fn srAuthored tm = tm.numfaces > SR_DENSE_FACES and tm.numverts < tm.numfaces and not srOneGroup tm

-- faces lying exactly on another face of the mesh (the same three corners: SketchUp's two-sided faces, a face
-- exported twice): they flicker in renders and spoil the smoothing (the two normals cancel out). One is kept.
global SR_DUP_FACES = 0
-- objects lying on another object's faces (filled by liftOverlaps, clean_scene.ms): no TurboSmooth for them
global LO_CONTACT = Dictionary #integer
global SR_CONTACT_KEPT = 0
fn srDupKey a = (sort a; local k = ""; for v in a do k += v as string + ","; k)
fn srDeleteDupFaces b = (
	local dup = #{}
	local seen = Dictionary #string
	if classof b == Editable_mesh then (
		local tm = b.mesh
		for i = 1 to tm.numfaces do (
			local f = getFace tm i
			local k = srDupKey #(f.x as integer, f.y as integer, f.z as integer)
			if hasDictValue seen k then dup[i] = true else seen[k] = true
		)
		if dup.numberSet > 0 do meshop.deleteFaces b dup delIsoVerts:true
	) else (
		for i = 1 to polyop.getNumFaces b do (
			local k = srDupKey (polyop.getFaceVerts b i)
			if hasDictValue seen k then dup[i] = true else seen[k] = true
		)
		if dup.numberSet > 0 do polyop.deleteFaces b dup delIsoVerts:true
	)
	SR_DUP_FACES += dup.numberSet
	dup.numberSet
)

-- a screen, a label or a trim drawn on a panel in the same plane, inside one mesh (SketchUp: a face of another
-- material over a face): the two fight in renders, in ragged patches of both colours. Where faces of two materials lie
-- in one plane (SR_PLANE_MM) one over the other, the smaller material's faces (the screen, the label) get vertices of
-- their own and are lifted SR_LIFT_MM off the panel, so they lie on it. Distances are in mm (the mesh's own units
-- times its scale, sc). Returns the faces lifted.
global SR_PLANE_MM = 0.1
global SR_LIFT_MM = 1.0     -- (more than the weld, SR_WELD_MM, so the two never weld again)
global SR_LIFTED = 0
fn srPointInTri p a b c n = (
	(dot (cross (b - a) (p - a)) n) >= 0 and (dot (cross (c - b) (p - b)) n) >= 0 and (dot (cross (a - c) (p - c)) n) >= 0
)
fn srLiftDecals o sc = (
	local tm = o.mesh                 -- (the node's: the base object's .mesh is a copy)
	local nf = tm.numfaces
	if nf < 2 do return 0
	local ids = #{}
	for i = 1 to nf do ids[getFaceMatID tm i] = true
	if ids.numberSet < 2 do return 0
	local eps = SR_PLANE_MM / sc
	-- planes: the face normal (either way round) and the distance from the origin, binned on two staggered grids
	-- (two faces a hair apart on either side of a bin's edge still meet in the other grid)
	local bins = Dictionary #string
	local info = for i = 1 to nf collect (
		local n = getFaceNormal tm i
		local f = getFace tm i
		local a = getVert tm f.x
		if n.x < -1e-6 or (abs n.x <= 1e-6 and (n.y < -1e-6 or (abs n.y <= 1e-6 and n.z < 0))) do n = -n
		local d = dot n a
		local kn = ((n.x * 50) as integer) as string + "," + ((n.y * 50) as integer) as string + "," + ((n.z * 50) as integer) as string
		for k in #(kn + "|" + ((floor (d / (4 * eps))) as integer) as string, kn + "/" + ((floor (d / (4 * eps) + 0.5)) as integer) as string) do
			if hasDictValue bins k then append bins[k] i else bins[k] = #(i)
		#(n, d)
	)
	local lift = #{}
	local up = Dictionary #integer       -- face -> the normal of the face it lies on (the panel's outside)
	for k in bins.keys do (
		local fs = bins[k]
		if fs.count < 2 do continue
		-- the area of each material in the plane
		local areas = Dictionary #integer
		for i in fs do (local id = getFaceMatID tm i; areas[id] = (if hasDictValue areas id then areas[id] else 0.0) + meshop.getFaceArea tm i)
		if areas.count < 2 do continue
		local small = undefined
		for id in areas.keys do if small == undefined or areas[id] < areas[small] do small = id
		-- the small material's faces whose centre lies on a face of another material (the same plane, over it)
		local others = for i in fs where getFaceMatID tm i != small collect i
		if fs.count * others.count > 4000000 do continue
		for i in fs where getFaceMatID tm i == small do (
			local c = meshop.getFaceCenter tm i
			local n = info[i][1]
			local over = 0
			for j in others while over == 0 do (
				if abs (info[j][2] - info[i][2]) > eps do continue
				local g = getFace tm j
				if srPointInTri c (getVert tm g.x) (getVert tm g.y) (getVert tm g.z) n do over = j
			)
			if over > 0 do (lift[i] = true; up[i] = getFaceNormal tm over)
		)
		-- and the small material's other faces in this plane (a label over a groove or a hole in its panel: lifting
		-- only some of its faces would leave steps between them, which render as dark lines)
		local binUp = undefined
		for i in fs where lift[i] while binUp == undefined do binUp = up[i]
		if binUp != undefined do for i in fs where getFaceMatID tm i == small and not lift[i] do (lift[i] = true; up[i] = binUp)
	)
	if lift.numberSet == 0 do return 0
	-- the lifted faces get vertices of their own (the panel keeps its own), moved along the panel's normal
	local nv = tm.numverts
	local copyOf = Dictionary #integer
	local extra = #()
	for i in lift do (
		local f = getFace tm i
		local nn = #()
		for v in #(f.x as integer, f.y as integer, f.z as integer) do (
			if not hasDictValue copyOf v do (
				append extra ((getVert tm v) + up[i] * (SR_LIFT_MM / sc))
				copyOf[v] = nv + extra.count
			)
			append nn copyOf[v]
		)
		up[i] = [nn[1], nn[2], nn[3]]
	)
	setNumVerts tm (nv + extra.count) true
	for k = 1 to extra.count do setVert tm (nv + k) extra[k]
	for i in lift do setFace tm i up[i]
	meshop.deleteIsoVerts tm
	update o
	SR_LIFTED += lift.numberSet
	lift.numberSet
)

-- weld and smooth the object's own mesh (its base object); returns false when it is not a mesh or a poly
fn srWeldSmooth o angleDeg = (
	local b = o.baseObject
	-- (a poly of several materials becomes a mesh, which the decals' lift works on; the shape stays)
	if classof b == Editable_Poly and polyop.getNumFaces b > 0 do (
		local ids = #{}
		for i = 1 to polyop.getNumFaces b do ids[polyop.getFaceMatID b i] = true
		if ids.numberSet > 1 do (convertToMesh o; b = o.baseObject)
	)
	if classof b == Editable_mesh then (
		if meshop.getNumFaces b == 0 do return false   -- (an empty mesh: nothing to smooth)
		local s = o.transform.scalepart
		local sc = (abs s.x + abs s.y + abs s.z) / 3.0
		meshop.weldVertsByThreshold b (srAll (meshop.getNumVerts b)) (srWeldDist o sc)
		srDeleteDupFaces b
		srLiftDecals o sc
		meshop.autoSmooth b (srAll (meshop.getNumFaces b)) angleDeg
		update o
		true
	) else if classof b == Editable_Poly then (
		if polyop.getNumFaces b == 0 do return false
		local s = o.transform.scalepart
		b.weldThreshold = srWeldDist o ((abs s.x + abs s.y + abs s.z) / 3.0)
		polyop.weldVertsByThreshold b (srAll (polyop.getNumVerts b))
		srDeleteDupFaces b
		b.autoSmoothThreshold = angleDeg
		polyop.setFaceSelection b (srAll (polyop.getNumFaces b))
		b.autosmooth()
		true
	) else false
)

fn srWeightedNormals = (
	local wn = Weighted_Normals()
	wn.useAreaWeight = true
	wn.useAngleWeight = true
	wn.useSmoothingGroups = true
	wn.useHardEdgeAngle = false
	wn
)

-- an object with modifiers (an Edit Poly someone added) is collapsed, which keeps what the modifiers did; an
-- instance is made unique first (collapsing it would collapse all of them)
fn srCollapse o = (
	if (InstanceMgr.GetInstances o &inst) > 1 do InstanceMgr.MakeObjectsUnique o #individual
	convertToMesh o
)

-- one object: weld and smooth its mesh, and subdivide it when it is round - once per shared mesh: instances share
-- their modifiers too, so the first one's TurboSmooth is theirs.
-- st = #(done, round, nSmooth, nSub, before, after): the running state, changed in place
fn srOne o angleDeg iters renderIters st = (
	local done = st[1]; local round = st[2]
	local key = getHandleByAnim o.baseObject
	-- (a snapshot: asking the node's own mesh re-evaluates the object on every question)
	local snap = snapshotAsMesh o
	local nf = snap.numfaces
	if nf > 0 do (
		if not hasDictValue done key do (
			done[key] = true
			round[key] = false
			if not srAuthored snap and srWeldSmooth o angleDeg do (
				delete snap
				snap = snapshotAsMesh o
				st[3] += 1
				-- (a dense mesh is fine enough as it is: subdividing it only multiplies its faces)
				round[key] = snap.numfaces <= SR_DENSE_FACES and (srCurvedShare snap) >= SR_ROUND_SHARE
				-- (an object lying flat on another's faces: subdivided, it would push through them)
				if round[key] and hasDictValue LO_CONTACT (getHandleByAnim o) do (round[key] = false; SR_CONTACT_KEPT += 1)
				if round[key] do (
					local ts = TurboSmooth()
					ts.iterations = iters
					ts.useRenderIterations = true
					ts.renderIterations = renderIters
					ts.sepBySmGroups = true
					ts.sepByMats = true
					ts.isolineDisplay = true
					ts.smoothResult = true
					addModifier o ts
				)
				-- the others: normals weighted by the faces' area, so that a big flat face stays flat and its rounded
				-- or bevelled rim takes the bend (without it, the long thin triangles around a slot, a hole or a bolt
				-- streak a flat panel with shading); the hard edges of the smoothing stay hard
				if not round[key] do addModifier o (srWeightedNormals())
			)
		)
		st[5] += nf
		if round[key] then (st[4] += 1; st[6] += nf * (4 ^ iters)) else st[6] += nf
	)
	delete snap
)

fn smoothRounds nodes angleDeg iters renderIters = (
	SR_SKIPPED = #()
	SR_DUP_FACES = 0
	SR_LIFTED = 0
	SR_CONTACT_KEPT = 0
	local geo = for o in nodes where isValidNode o and superclassof o == GeometryClass and canConvertTo o TriMeshGeometry collect o
	for o in geo where o.modifiers.count > 0 do
		try (srCollapse o) catch (append SR_SKIPPED (o.name + ": " + getCurrentException()))
	local st = #(Dictionary #integer, Dictionary #integer, 0, 0, 0, 0)
	for o in geo do
		try (srOne o angleDeg iters renderIters st) catch (append SR_SKIPPED (o.name + ": " + getCurrentException()))
	#(st[3], st[4], st[5], st[6])
)
