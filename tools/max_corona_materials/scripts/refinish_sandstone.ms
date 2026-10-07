-- Step "refinish" of the Sand Stone finish: a scene re-finished in the Sand Stone materials, saved as a new file.
-- Run by corona_materials.bat, which defines:
--   ING_WORK       the work folder: sandstone_materials.tsv, sandstone_map.tsv, sandstone_swatches.tsv
--   ING_SCENE      the scene (.max); it is only read
--   ING_ACTIONS    <scene>_actions.tsv: equipment \t keep|remove|recolour \t why
--   ING_OUT        the file to write (.max)
--   ING_MAPS       the folder of the maps (ends with \)
--   ING_LAYER      the layer of the recoloured equipment
--   ING_FALLBACK   the Sand Stone material of a scene material the map does not name
--   ING_LOG        the log to write; its last line is DONE or ERROR: ...
--   ING_SMOOTH     true: smoother round parts (smooth_rounds.ms), with ING_SMOOTH_ANGLE, ING_SMOOTH_ITERS (viewport)
--                  and ING_SMOOTH_RENDER_ITERS (renders)
--   ING_CHAMFER    true: rounded edges (chamfer_edges.ms; after the smoothing, which it needs), with
--                  ING_CHAMFER_ANGLE, ING_CHAMFER_RATIO and ING_CHAMFER_MIN
-- What it does, in order: removes the equipment marked remove (a black version of equipment the scenes have in Sand
-- Stone too); puts the equipment marked recolour on ING_LAYER; removes the colour swatches (small simple objects made
-- only of swatch colours) and the free-space zones (flat rectangles of a zone colour); deletes the objects that are
-- the same surface as another (clean_scene.ms); gives every object the Sand Stone material of its material (inside
-- multi-materials too); makes the round parts smoother (welded, duplicate faces deleted, smoothed by angle, round
-- objects subdivided, the others' normals weighted); gives the sharp edges of plain solid parts a real rounded
-- chamfer.
if ING_WORK == undefined or ING_SCENE == undefined or ING_OUT == undefined do throw "run this script with corona_materials.bat (it sets the paths)"
fileIn (getFilenamePath (getSourceFileName()) + "sandstone_materials.ms")
fileIn (getFilenamePath (getSourceFileName()) + "smooth_rounds.ms")
fileIn (getFilenamePath (getSourceFileName()) + "chamfer_edges.ms")
fileIn (getFilenamePath (getSourceFileName()) + "clean_scene.ms")
global LOGF
-- a colour swatch (a small cube in a pure colour beside a machine): at most this big (scene units) and this simple
global SWATCH_MAX_MM = 100
global SWATCH_MAX_FACES = 24
fn lg s = (format "% %\n" (localTime) s to:LOGF; flush LOGF)

fn readTsv path = (
	if not doesFileExist path do return #()
	for line in filterString ((dotNetClass "System.IO.File").ReadAllText path) "\r\n" collect (filterString line "\t" splitEmptyTokens:true)
)
fn allDescendants root = (
	local out = #(); local stack = #(root)
	while stack.count > 0 do (
		local c = stack[stack.count]; deleteItem stack stack.count
		append out c
		for ch in c.children do append stack ch
	)
	out
)
fn equipmentOf = (
	local root = getNodeByName "Model"
	local eq = if isValidNode root then (for c in root.children collect c) else #()
	for o in objects where o.parent == undefined and o != root and (isGroupHead o or superclassof o == GeometryClass) do append eq o
	eq
)

global RF_MAP, RF_UNKNOWN
fn targetFor src = (
	if src == undefined do return undefined
	local ss = if hasDictValue RF_MAP src.name then RF_MAP[src.name] else (
		RF_UNKNOWN[src.name] = true
		ING_FALLBACK
	)
	ssMaterialFor ss src
)

fn refinishMain = (
	LOGF = createFile ING_LOG
	try (
		loadMaxFile ING_SCENE quiet:true useFileUnits:true
		lg ("loaded " + ING_SCENE + ": " + objects.count as string + " objects")
		SS_MAPS = ING_MAPS
		lg ("Sand Stone materials: " + (ssLoadSpecs (ING_WORK + "sandstone_materials.tsv")) as string)
		RF_MAP = Dictionary #string
		for f in readTsv (ING_WORK + "sandstone_map.tsv") where f.count >= 2 do RF_MAP[f[1]] = f[2]
		RF_UNKNOWN = Dictionary #string
		local swatch = Dictionary #string
		for f in readTsv (ING_WORK + "sandstone_swatches.tsv") where f.count >= 1 do swatch[f[1]] = true
		local action = Dictionary #string
		for f in readTsv ING_ACTIONS where f.count >= 2 do action[f[1]] = f[2]

		------------------------------------------------------------ equipment: remove, recolour
		local toDelete = #(); local toLayer = #()
		local nRemoved = 0; local nRecoloured = 0
		for E in equipmentOf() do (
			local a = if hasDictValue action E.name then action[E.name] else "keep"
			if a == "remove" then (join toDelete (allDescendants E); nRemoved += 1)
			else if a == "recolour" do (join toLayer (allDescendants E); nRecoloured += 1)
		)
		if toLayer.count > 0 do (
			local lay = LayerManager.getLayerFromName ING_LAYER
			if lay == undefined do lay = LayerManager.newLayerFromName ING_LAYER
			for o in toLayer where isValidNode o do lay.addNode o
		)
		if toDelete.count > 0 do delete (for o in toDelete where isValidNode o collect o)
		lg ("equipment removed (black: a Sand Stone twin, or hidden): " + nRemoved as string + ", recoloured (black only): " + nRecoloured as string + " on layer '" + ING_LAYER + "'")

		------------------------------------------------------------ colour swatches
		local swatches = #()
		for o in geometry where isValidNode o and o.material != undefined do (
			local d = o.max - o.min
			if (amax #(d.x, d.y, d.z)) > SWATCH_MAX_MM do continue
			local nf = try ((getPolygonCount o)[1]) catch 999
			if nf > SWATCH_MAX_FACES do continue
			local subs = if classof o.material == MultiMaterial then (for s in o.material.materialList where s != undefined collect s) else #(o.material)
			local all = subs.count > 0
			for s in subs while all do all = hasDictValue swatch s.name
			if all do append swatches o
		)
		if swatches.count > 0 do delete swatches
		lg ("colour swatches removed: " + swatches.count as string)

		------------------------------------------------------------ free-space zones (flat rectangles on the floor)
		-- a zone: flat, a few faces, at least 300 mm both ways, only in swatch / zone colours
		local zone = Dictionary #string
		for f in readTsv (ING_WORK + "sandstone_zones.tsv") where f.count >= 1 do zone[f[1]] = true
		for k in swatch.keys do zone[k] = true
		local zones = #()
		for o in geometry where isValidNode o and o.material != undefined do (
			local d = o.max - o.min
			local dims = #(d.x, d.y, d.z); sort dims
			if dims[1] > 1.0 or dims[2] < 300 do continue
			local nf = try ((getPolygonCount o)[1]) catch 999
			if nf > 8 do continue
			local subs = if classof o.material == MultiMaterial then (for s in o.material.materialList where s != undefined collect s) else #(o.material)
			local all = subs.count > 0
			for s in subs while all do all = hasDictValue zone s.name
			if all do append zones o
		)
		if zones.count > 0 do delete zones
		lg ("free-space zones removed: " + zones.count as string)

		------------------------------------------------------------ objects lying on each other
		-- the same mesh twice at the same place (exported twice, or a copy left behind): the two flicker in renders,
		-- in two colours when their materials differ. One is kept: the one whose material has the more meaningful name
		local coin = removeCoincident (for o in geometry where isValidNode o collect o)
		lg ("objects lying on another (the same surface twice) removed: " + coin[1] as string + " (of another material: " + coin[2] as string + ")")
		for s in RC_LOG do lg ("  the same surface twice: deleted " + s)

		------------------------------------------------------------ screens and labels lying on panels
		-- (on the meshes themselves: an object with modifiers is collapsed first, as the smoothing does)
		for o in geometry where isValidNode o and o.modifiers.count > 0 and canConvertTo o TriMeshGeometry do try (srCollapse o) catch ()
		local t0 = timeStamp()
		local nLift = liftOverlaps (for o in geometry where isValidNode o collect o)
		lg ("objects lying in the plane of a bigger one (screens, labels, pads), lifted off it: " + LO_LOG.count as string + " (" + nLift as string + " faces; objects touching another face to face: " + LO_CONTACT.count as string + "; " + ((timeStamp() - t0) / 1000) as string + " s)")
		for s in LO_LOG do lg ("  lifted " + s)

		------------------------------------------------------------ materials
		local multis = Dictionary #string
		local n = 0
		for o in objects where superclassof o == GeometryClass and o.material != undefined do (
			local m = o.material
			if classof m == MultiMaterial then (
				local key = (getHandleByAnim m) as string
				if not hasDictValue multis key do (
					local nm = MultiMaterial numsubs:m.numsubs
					nm.name = m.name
					nm.materialIDList = m.materialIDList
					for i = 1 to m.numsubs do nm.materialList[i] = targetFor m.materialList[i]
					multis[key] = nm
				)
				o.material = multis[key]
			) else o.material = targetFor m
			n += 1
		)
		lg ("objects re-finished: " + n as string + " (multi-materials: " + multis.count as string + ")")
		if RF_UNKNOWN.count > 0 do lg ("materials not in the map (given " + ING_FALLBACK + "): " + (for k in RF_UNKNOWN.keys collect k) as string)
		local used = Dictionary #string
		for o in objects where o.material != undefined do (
			local subs = if classof o.material == MultiMaterial then (for s in o.material.materialList where s != undefined collect s) else #(o.material)
			for s in subs do used[s.name] = true
		)
		lg ("materials in the scene now: " + used.count as string)

		------------------------------------------------------------ smoother round parts
		if ING_SMOOTH == true do (
			local t0 = timeStamp()
			local res = smoothRounds (for o in objects where superclassof o == GeometryClass collect o) ING_SMOOTH_ANGLE ING_SMOOTH_ITERS ING_SMOOTH_RENDER_ITERS
			if SR_SKIPPED.count > 0 do lg ("round parts: " + SR_SKIPPED.count as string + " objects left as they were (they could not be smoothed): " + (for i = 1 to amin 10 SR_SKIPPED.count collect SR_SKIPPED[i]) as string)
			lg ("round parts: " + res[1] as string + " meshes welded and smoothed (duplicate faces deleted: " + SR_DUP_FACES as string + ", faces of screens and labels lifted off their panel: " + SR_LIFTED as string + "; round objects lying on another, not subdivided: " + SR_CONTACT_KEPT as string + "), " + res[2] as string + " round objects subdivided (TurboSmooth " + ING_SMOOTH_ITERS as string + " / renders " + ING_SMOOTH_RENDER_ITERS as string + "); faces in the viewport " + res[3] as string + " -> " + res[4] as string + " (" + ((timeStamp() - t0) / 1000) as string + " s)")
		)

		------------------------------------------------------------ rounded edges
		if ING_CHAMFER == true do (
			local t0 = timeStamp()
			local st = chamferEdges (for o in objects where superclassof o == GeometryClass collect o) ING_CHAMFER_ANGLE ING_CHAMFER_RATIO ING_CHAMFER_MIN
			lg ("rounded edges: " + st[#chamfered] as string + " meshes chamfered; kept as they were: " + st[#small] as string + " small, " + st[#thin] as string + " thin, " + st[#curved] as string + " curved (their TurboSmooth), " + st[#unclean] as string + " not a plain solid, " + st[#mixed] as string + " of several materials, " + st[#smooth] as string + " without sharp edges, " + st[#big] as string + " dense, " + st[#failed] as string + " whose chamfer failed its check; faces " + st[#before] as string + " -> " + st[#after] as string + " (" + ((timeStamp() - t0) / 1000) as string + " s)")
			if CE_SKIPPED.count > 0 do lg ("rounded edges: chamfers taken off again (first 10): " + (for i = 1 to amin 10 CE_SKIPPED.count collect CE_SKIPPED[i]) as string)
		)

		------------------------------------------------------------ save
		renderers.current = CoronaRenderer()
		for i = 1 to meditMaterials.count do meditMaterials[i] = ssMaterial "SS_Speckled_Stone"
		local i = 0
		for k in SS_SPECS.keys where SS_SPECS[k]["kind"] == "plain" and i < 24 do (i += 1; meditMaterials[i] = ssMaterial k)
		makeDir (getFilenamePath ING_OUT) all:true
		if doesFileExist ING_OUT do deleteFile ING_OUT
		saveMaxFile ING_OUT quiet:true
		lg ("saved " + ING_OUT + ": " + objects.count as string + " objects")
		lg "DONE"
	) catch (
		lg ("ERROR: " + getCurrentException())
	)
	close LOGF
)
refinishMain()
