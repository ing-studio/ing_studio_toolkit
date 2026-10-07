-- Step "survey" of the Sand Stone finish: what equipment a scene has and what it is made of. Run by
-- corona_materials.bat, which defines:
--   ING_WORK     the work folder
--   ING_LOG      the log to write; its last line is DONE or ERROR: ...
--   ING_SCENE    the scene (.max)
--   ING_SURVEY   the file to write: JSON lines
--                  {"eq": name, "hidden": true|false (all of it hidden), "nodes": n, "faces": n, "min": [x,y,z],
--                   "max": [x,y,z], "mats": [{"m", "f", "rgb"}]}
--                  {"material": name, "rgb": [r,g,b] or null}
-- Equipment = the children of the node "Model" (a SketchUp import puts every component there) and the scene's
-- other top-level groups and objects.
if ING_WORK == undefined or ING_SCENE == undefined or ING_SURVEY == undefined do throw "run this script with corona_materials.bat (it sets the paths)"

fn jstr s = (
	s = s as string
	s = substituteString s "\\" "\\\\"
	s = substituteString s "\"" "\\\""
	"\"" + s + "\""
)
fn p3 p = "[" + ((p.x as integer) as string) + "," + ((p.y as integer) as string) + "," + ((p.z as integer) as string) + "]"
-- the colour value as stored in the material (an imported SketchUp colour keeps its 0..255 numbers)
fn rgbOf m = (
	if m == undefined do return "null"
	local c = undefined
	if hasProperty m #colorDiffuse then c = m.colorDiffuse
	else if hasProperty m #baseColor then c = m.baseColor
	else if hasProperty m #diffuse then c = m.diffuse
	if classof c != color do return "null"
	"[" + (c.r as integer) as string + "," + (c.g as integer) as string + "," + (c.b as integer) as string + "]"
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

fn surveyMain = (
	local logf = createFile ING_LOG
	local f = createFile ING_SURVEY
	try (
		loadMaxFile ING_SCENE quiet:true useFileUnits:true
		format "loaded % (% objects)\n" ING_SCENE objects.count to:logf
		local allMats = Dictionary #string
		for E in equipmentOf() do (
			local desc = allDescendants E
			local faces = Dictionary #string
			local bmin = [1e12,1e12,1e12]; local bmax = [-1e12,-1e12,-1e12]
			local total = 0; local shown = 0
			for o in desc where superclassof o == GeometryClass do (
				if not o.isHiddenInVpt do shown += 1
				bmin = [amin bmin.x o.min.x, amin bmin.y o.min.y, amin bmin.z o.min.z]
				bmax = [amax bmax.x o.max.x, amax bmax.y o.max.y, amax bmax.z o.max.z]
				local nf = try ((getPolygonCount o)[1]) catch 0
				total += nf
				local m = o.material
				local subs = if classof m == MultiMaterial then (for s in m.materialList where s != undefined collect s) else #(m)
				for s in subs where s != undefined do (
					faces[s.name] = (if hasDictValue faces s.name then faces[s.name] else 0) + nf / (amax 1 subs.count)
					allMats[s.name] = rgbOf s
				)
			)
			if total == 0 do continue
			local s = "{\"eq\":" + jstr E.name + ",\"hidden\":" + (shown == 0) as string + ",\"nodes\":" + desc.count as string + ",\"faces\":" + total as string + ",\"min\":" + p3 bmin + ",\"max\":" + p3 bmax + ",\"mats\":["
			local first = true
			for k in faces.keys do (
				s += (if first then "" else ",") + "{\"m\":" + jstr k + ",\"f\":" + faces[k] as string + ",\"rgb\":" + allMats[k] + "}"
				first = false
			)
			format "%]}\n" s to:f
		)
		for k in allMats.keys do format "{\"material\":%,\"rgb\":%}\n" (jstr k) allMats[k] to:f
		format "DONE\n" to:logf
	) catch (
		format "ERROR: %\n" (getCurrentException()) to:logf
	)
	close f
	close logf
)
surveyMain()
