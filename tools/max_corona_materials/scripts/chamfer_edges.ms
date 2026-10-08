-- Rounded edges: SketchUp and CAD models have knife-sharp edges, which nothing made in real life has (a steel bar's
-- corner is rounded a few millimetres, a moulded cover's more, a pad's a lot). fileIn'd by refinish_sandstone.ms after
-- smooth_rounds.ms (it needs welded meshes, smoothed by angle); defines
--   chamferEdges nodes angleDeg ratio minMM -> a Dictionary: how many objects for each key of CE_KEYS, and the
--                                              faces #before and #after
-- Every edge sharper than angleDeg gets a real rounded chamfer: a Chamfer modifier at the bottom of the stack, live, so
-- its amount can still be changed. Its size is the part's: ratio x the object's smallest dimension, at most a quarter
-- of its wall's thickness and the chamfer_mm of its Sand Stone material (SS_SPECS) - a 40 mm bar gets 6 mm, a 3 mm
-- sheet 0.75 mm, a bolt nothing (below minMM). A Weighted Normals modifier on top keeps the flat faces flat and lets
-- the chamfer shade like a fillet.
-- A chamfer tears or folds what is not a solid, so only those get one: every object but the round ones (a TurboSmooth
-- over a chamfer serrates it: round objects keep their TurboSmooth), of one material, closed but for a few open edges,
-- its polygons of not too many sides. Each chamfer is worked out and checked - nothing torn open, no face collapsed or
-- folded, nothing sticking out - and taken off again when it fails: the check, not a guess about the shape, decides.
-- The edges left sharp are still rounded in renders by Corona Round Edges (round_mm, in every Sand Stone material).
-- Instances share the chamfer.
global CE_KEYS = #(#chamfered, #small, #thin, #curved, #mixed, #unclean, #smooth, #big, #failed)
global CE_SKIPPED = #()          -- objects whose chamfer failed (names and why), for the log
global CE_WHY_FAILED = ""        -- why the last chamfer checked was not sound
global CE_MAX_FACES = 100000     -- bigger meshes are well-made (or too big to check): left as they are
global CE_MAX_RATIO = 12.0       -- a chamfer that multiplies the faces more than this: too many small edges
global CE_MAX_CURVED = SR_ROUND_SHARE  -- objects with more curved surface (of their area, srCurvedShare) are round
global CE_MAX_OPEN = 0.1         -- meshes with more open edges (of all their edges) are surfaces, not solids
global CE_MAX_SIDES = 40         -- polygons with more sides (a big disc's cap) collapse

fn ceArea tm = (local a = 0.0; for i = 1 to tm.numfaces do a += meshop.getFaceArea tm i; a)

-- the volume a closed mesh holds (tetrahedra from its centre to its faces)
fn ceVolume tm = (
	local c = [0, 0, 0]
	for i = 1 to tm.numverts do c += getVert tm i
	c /= amax 1 tm.numverts
	local v = 0.0
	for i = 1 to tm.numfaces do (
		local f = getFace tm i
		v += dot ((getVert tm f.x) - c) (cross ((getVert tm f.y) - c) ((getVert tm f.z) - c))
	)
	abs (v / 6.0)
)

-- the Sand Stone material's chamfer_mm (logos and displays are "SS_x - source"); 0 = never chamfered
fn ceMaterialMM mtl = (
	if mtl == undefined or SS_SPECS == undefined do return 0.0
	local nm = mtl.name
	local i = findString nm " - "
	if i != undefined do nm = substring nm 1 (i - 1)
	if hasDictValue SS_SPECS nm then ssNum SS_SPECS[nm] "chamfer_mm" 0.0 else 0.0
)

-- the one material of the mesh, or undefined when its faces have several (a chamfer on a material border mixes them)
fn ceOneMaterial o tm = (
	local m = o.material
	if classof m != Multimaterial do return m
	local id = if tm.numfaces > 0 then getFaceMatID tm 1 else 1
	for i = 2 to tm.numfaces do if getFaceMatID tm i != id do return undefined
	local k = findItem m.materialIDList id
	if k == 0 then m.materialList[1 + (mod (id - 1) m.materialList.count)] else m.materialList[k]
)

-- the mesh's shape when a chamfer can work on it, #(open edges, area, length of the edges sharper than angleDeg), or
-- undefined: too many open edges, an edge or a vertex shared by separate surfaces (3ds Max splits those when the mesh
-- becomes a poly, which the Chamfer modifier works on), or a polygon of many sides. (Concave polygons - a plate's
-- notch, a face around a hole - mostly chamfer well; when one does not, the check after the chamfer finds it.)
fn ceShape tm angleDeg = (
	local nOpen = (meshop.getOpenEdges tm).numberSet
	if nOpen > CE_MAX_OPEN * 1.5 * tm.numfaces do return undefined
	local used = (meshop.getVertsUsingFace tm #{1..tm.numfaces}).numberSet
	local t = mesh mesh:tm
	convertToPoly t
	local ok = polyop.getNumVerts t == used
	local nPoly = polyop.getNumFaces t
	for f = 1 to nPoly while ok do if polyop.getFaceDeg t f > CE_MAX_SIDES do ok = false
	local hardLen = 0.0
	if ok do (
		local normals = for f = 1 to nPoly collect polyop.getFaceNormal t f
		local cosHard = cos angleDeg
		for e = 1 to polyop.getNumEdges t do (
			local fs = polyop.getEdgeFaces t e
			if fs.count == 2 and (dot normals[fs[1]] normals[fs[2]]) < cosHard do (
				local vs = polyop.getEdgeVerts t e
				hardLen += distance (polyop.getVert t vs[1]) (polyop.getVert t vs[2])
			)
		)
	)
	delete t
	if ok then #(nOpen, ceArea tm, hardLen) else undefined
)

-- the chamfered mesh is sound: it tore nothing open, lost no more surface than a chamfer along the sharp edges takes
-- (about its amount per millimetre of edge at most; a collapsed face loses far more) and gained none, sticks out
-- nowhere, and has not too many faces. Its face count, or -1 (CE_WHY_FAILED says why)
fn ceSound o shape amt nf bbMin bbMax = (
	local m = snapshotAsMesh o
	local a = ceArea m
	local a0 = shape[2]
	local d = o.max - o.min
	local tol = 0.001 * (amax #(d.x, d.y, d.z)) + 0.01
	CE_WHY_FAILED = if m.numfaces > nf * CE_MAX_RATIO then "too many faces"
		else if (meshop.getOpenEdges m).numberSet > 3 * shape[1] then "torn open"
		else if a > a0 * 1.002 or a < a0 - 1.2 * amt * shape[3] - 0.002 * a0 then "a face collapsed or folded"
		else if o.min.x < bbMin.x - tol or o.min.y < bbMin.y - tol or o.min.z < bbMin.z - tol or \
			o.max.x > bbMax.x + tol or o.max.y > bbMax.y + tol or o.max.z > bbMax.z + tol then "sticks out"
		else ""
	local n = m.numfaces
	delete m
	if CE_WHY_FAILED == "" then n else -1
)

fn ceAdd o amt segs angleDeg = (
	local s = o.transform.scalepart
	local sc = (abs s.x + abs s.y + abs s.z) / 3.0
	local c = Chamfer()
	c.selectionoption = 0              -- every edge ...
	c.useminangle = true               -- ... sharper than angleDeg
	c.minangle = angleDeg
	c.amount = amt / sc                -- (the mesh's own units)
	c.segments = segs
	c.miteringType = 1                 -- (the radial one serrates edges that follow a curve)
	c.quadIntersectionMode = false     -- no extra lines across the flat faces
	c.limiteffect = true               -- never more than the neighbouring edges allow
	c.smooth = true
	c.smoothtype = 1                   -- the chamfer smooth in itself
	c.smooththreshold = 30.0
	if o.modifiers.count == 0 then addModifier o c else addModifier o c before:o.modifiers.count
	local wn = Weighted_Normals()
	wn.useSmoothingGroups = false
	wn.useHardEdgeAngle = true
	wn.hardEdgeAngle = 46.0            -- the chamfer's facets (45 degrees at most) blend; sharper edges stay hard
	addModifier o wn
	#(c, wn)
)

fn ceRemove o mods = for m in mods do (local i = findItem o.modifiers m; if i > 0 do deleteModifier o i)

-- why an object keeps its edges (a key of CE_KEYS), or #(#chamfer, amount, shape)
fn ceWhy o tm angleDeg ratio minMM = (
	if tm.numfaces > CE_MAX_FACES or srAuthored tm do return #(#big)
	for m in o.modifiers where classof m == TurboSmooth do return #(#curved)   -- (a round object: smooth_rounds.ms)
	if o.material == undefined do return #(#small)   -- (no material: no chamfer_mm)
	local mtl = ceOneMaterial o tm
	if mtl == undefined do return #(#mixed)
	local d = o.max - o.min
	local amt = amin #(ratio * (amin #(d.x, d.y, d.z)), ceMaterialMM mtl)
	if amt < minMM do return #(#small)
	if (srCurvedShare tm) > CE_MAX_CURVED do return #(#curved)
	local shape = ceShape tm angleDeg
	if shape == undefined do return #(#unclean)
	if shape[3] == 0 do return #(#smooth)
	-- a bent sheet or a thin wall is far thinner than its box: twice its volume over its surface is its thickness
	-- (a plate's; half a square bar's side), and a quarter of that the most a chamfer can take from both sides
	amt = amin amt (0.5 * (ceVolume tm) / shape[2])
	if amt < minMM do return #(#thin)
	#(#chamfer, amt, shape)
)

-- one object (the first of its instances); st: the counts and faces, changed in place
fn ceOne o angleDeg ratio minMM st = (
	local snap = snapshotAsMesh o
	local nf = snap.numfaces
	st[#before] += nf
	local why = if nf == 0 then #(#small) else ceWhy o snap angleDeg ratio minMM
	delete snap
	if why[1] != #chamfer do (st[why[1]] += 1; st[#after] += nf; return false)
	local amt = why[2]; local shape = why[3]
	local segs = if amt < 2.0 then 1 else if amt < 5.0 then 2 else 3
	local bbMin = o.min; local bbMax = o.max
	-- the smoothing's Weighted Normals (smooth_rounds.ms) makes way for the chamfer's own, and comes back when the
	-- chamfer is taken off
	local hadWN = false
	for i = o.modifiers.count to 1 by -1 where classof o.modifiers[i] == Weighted_Normals do (deleteModifier o i; hadWN = true)
	local mods = ceAdd o amt segs angleDeg
	-- worked out now, so that a chamfer that fails is taken off here and not met when the scene is opened
	local after = try (ceSound o shape amt nf bbMin bbMax) catch (CE_WHY_FAILED = getCurrentException(); -1)
	if after < 0 and segs > 1 do (
		mods[1].segments = 1
		after = try (ceSound o shape amt nf bbMin bbMax) catch (CE_WHY_FAILED = getCurrentException(); -1)
	)
	if after < 0 then (
		append CE_SKIPPED (o.name + ": " + CE_WHY_FAILED)
		ceRemove o mods
		if hadWN do addModifier o (srWeightedNormals())
		st[#failed] += 1; st[#after] += nf
		false
	) else (st[#chamfered] += 1; st[#after] += after; true)
)

fn chamferEdges nodes angleDeg ratio minMM = (
	CE_SKIPPED = #()
	local st = Dictionary #name
	for k in CE_KEYS do st[k] = 0
	st[#before] = 0; st[#after] = 0
	local done = Dictionary #integer
	for o in nodes where isValidNode o and superclassof o == GeometryClass and canConvertTo o TriMeshGeometry do (
		local key = getHandleByAnim o.baseObject
		if hasDictValue done key do continue    -- an instance: it has the chamfer of the first one
		done[key] = true
		try (ceOne o angleDeg ratio minMM st) catch (append CE_SKIPPED (o.name + ": " + getCurrentException()); st[#failed] += 1)
	)
	st
)
