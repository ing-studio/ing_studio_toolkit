-- Step "import": the model into 3ds Max (an FBX is imported in millimetres; a .max is opened), saved as the raw
-- import, and its materials listed with how many meshes use them and their colour (the input of the part map).
-- Run by corona_materials.bat, which defines:
--   ING_MODEL       the model: .fbx or .max
--   ING_RAW         the raw import to write (.max)
--   ING_WORK        the work folder: model_materials.json, import.log
if ING_WORK == undefined or ING_MODEL == undefined or ING_RAW == undefined do throw "run this script with corona_materials.bat (it sets the paths)"

global LOGF

fn lg s = (format "% %\n" (localTime) s to:LOGF; flush LOGF)

fn jstr s = (
	s = s as string
	s = substituteString s "\\" "\\\\"
	s = substituteString s "\"" "\\\""
	"\"" + s + "\""
)

-- the colour a material shows: its diffuse / base colour, whatever its class
fn mtlColor m = (
	for p in #(#base_color, #diffuse, #colorDiffuse, #color) where hasProperty m p do (
		local c = getProperty m p
		if classof c == Color do return c
	)
	color 128 128 128
)

-- the leaf materials an object uses: its material, or the sub-materials its faces use
fn usedLeaves o = (
	local m = o.material
	if m == undefined do return #()
	if classof m != MultiMaterial do return #(m)
	local out = #()
	local tm = try (snapshotAsMesh o) catch undefined
	if tm == undefined do return (for s in m.materialList where s != undefined collect s)
	local ids = #()
	for fi = 1 to tm.numfaces do appendIfUnique ids (getFaceMatID tm fi)
	for id in ids do (
		local idx = findItem m.materialIDList id
		if idx == 0 do idx = (mod (id - 1) m.numsubs) as integer + 1
		local s = m.materialList[idx]
		if s != undefined do appendIfUnique out s
	)
	out
)

fn main = (
	LOGF = createFile (ING_WORK + "import.log")
	try (
		if matchPattern ING_MODEL pattern:"*.max" then (
			loadMaxFile ING_MODEL quiet:true
			lg ("opened " + ING_MODEL)
		) else (
			resetMaxFile #noPrompt
			units.SystemType = #millimeters
			units.DisplayType = #metric
			units.MetricType = #millimeters
			FBXImporterSetParam "ResetImport"
			FBXImporterSetParam "Mode" #create
			FBXImporterSetParam "Cameras" false
			FBXImporterSetParam "Lights" false
			FBXImporterSetParam "Animation" false
			FBXImporterSetParam "SmoothingGroups" true
			FBXImporterSetParam "ScaleConversion" true
			FBXImporterSetParam "ConvertUnit" "mm"
			FBXImporterSetParam "UpAxis" "Z"
			FBXImporterSetParam "GenerateLog" false
			lg ("importing " + ING_MODEL + " ...")
			local ok = importFile ING_MODEL #noPrompt using:FBXIMP
			lg ("import returned " + ok as string + ", objects: " + objects.count as string)
			if objects.count == 0 do throw "the FBX import produced no objects"
		)
		saveMaxFile ING_RAW quiet:true
		lg ("raw import saved: " + ING_RAW)

		-- materials: name -> #(meshes, colour)
		local used = Dictionary #string
		for o in objects where superclassof o == GeometryClass do (
			for m in usedLeaves o do (
				if hasDictValue used m.name then (used[m.name])[1] += 1
				else used[m.name] = #(1, mtlColor m)
			)
		)
		local f = createFile (ING_WORK + "model_materials.json")
		format "[\n" to:f
		local i = 0
		for k in used.keys do (
			i += 1
			local v = used[k]
			local c = v[2]
			format "%{\"name\":%,\"meshes\":%,\"rgb\":[%,%,%]}\n" (if i > 1 then "," else "") (jstr k) v[1] \
				((c.r + 0.5) as integer) ((c.g + 0.5) as integer) ((c.b + 0.5) as integer) to:f
		)
		format "]\n" to:f
		close f
		lg ("materials listed: " + used.count as string)
		lg "DONE"
	) catch (
		lg ("ERROR: " + getCurrentException())
	)
	close LOGF
)
main()
