-- Step "combine" of the Sand Stone finish: the re-finished scenes put together in one file. Run by
-- corona_materials.bat, which defines:
--   ING_PARTS      a text file: one re-finished scene per line, \t, the name of its dummy (refinish_sandstone.ms put
--                  all the scene's equipment under a dummy of that name, arranged in rows from the origin)
--   ING_OUT        the file to write (.max)
--   ING_GAP        the space between two pieces of equipment (mm); the scenes are 4 times that apart
--   ING_LOG        the log to write; its last line is DONE or ERROR: ...
-- The scenes are merged one after the other, each one's dummy moved so that the scenes lie side by side along -Y, in
-- their order. Materials of the same name are one material (the Sand Stone materials are the same in every scene;
-- each scene's multi-materials carry its name); layers of the same name are one layer.
if ING_PARTS == undefined or ING_OUT == undefined do throw "run this script with corona_materials.bat (it sets the paths)"
global LOGF
fn lg s = (format "% %\n" (localTime) s to:LOGF; flush LOGF)
fn allDescendants root = (
	local out = #(); local stack = #(root)
	while stack.count > 0 do (
		local c = stack[stack.count]; deleteItem stack stack.count
		append out c
		for ch in c.children do append stack ch
	)
	out
)

fn combineMain = (
	LOGF = createFile ING_LOG
	try (
		resetMaxFile #noPrompt
		-- (the scenes are in millimetres: merged into a scene of other units, 3ds Max would rescale them)
		units.SystemType = #millimeters
		units.SystemScale = 1
		units.DisplayType = #metric
		units.MetricType = #millimeters
		local lines = for ln in filterString ((dotNetClass "System.IO.File").ReadAllText ING_PARTS) "\r\n" collect (filterString ln "\t")
		local y = 0.0
		for f in lines where f.count >= 2 do (
			local before = objects.count
			mergeMAXFile f[1] #mergeDups #useSceneMtlDups #neverReparent #noRedraw quiet:true
			local part = getNodeByName f[2] exact:true
			if not isValidNode part do throw ("no dummy '" + f[2] + "' in " + f[1])
			local bmin = [1e12, 1e12, 1e12]; local bmax = [-1e12, -1e12, -1e12]
			for o in allDescendants part where superclassof o == GeometryClass do (
				bmin = [amin bmin.x o.min.x, amin bmin.y o.min.y, amin bmin.z o.min.z]
				bmax = [amax bmax.x o.max.x, amax bmax.y o.max.y, amax bmax.z o.max.z]
			)
			if bmin.x < bmax.x do (
				move part [-bmin.x, y - bmax.y, 0]
				y -= (bmax.y - bmin.y) + 4 * ING_GAP
			)
			lg ("merged " + f[1] + ": " + (objects.count - before) as string + " objects, '" + f[2] + "' with " + part.children.count as string + " equipment")
		)
		local used = Dictionary #string
		for o in objects where o.material != undefined do (
			local subs = if classof o.material == MultiMaterial then (for s in o.material.materialList where s != undefined collect s) else #(o.material)
			for s in subs do used[s.name] = true
		)
		lg ("materials in the scene: " + used.count as string)
		-- the Sand Stone materials in the Material Editor's slots
		local slot = Dictionary #string
		for o in objects where o.material != undefined and slot.count < 24 do (
			local subs = if classof o.material == MultiMaterial then (for s in o.material.materialList where s != undefined collect s) else #(o.material)
			for s in subs where slot.count < 24 and matchPattern s.name pattern:"SS_*" and findString s.name " - " == undefined and not hasDictValue slot s.name do (
				slot[s.name] = true
				meditMaterials[slot.count] = s
			)
		)
		renderers.current = CoronaRenderer()
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
combineMain()
