-- Dump materials of the reference scene to JSON and save them as a .mat library
global WORK = @"C:\Users\user\AppData\Local\Temp\claude\C--Users-user-Desktop-tbilisyan-test\0e5bd58f-86c7-4cab-84f0-266e1c1e110b\scratchpad\"
global REF = @"C:\Users\user\Desktop\tbilisyan test\ing_studio_toolkit\3d max material\technogym_set_sandstone_max2019_corona6_completed.max"

fn jstr s = (
	s = s as string
	s = substituteString s "\\" "\\\\"
	s = substituteString s "\"" "\\\""
	"\"" + s + "\""
)

fn texList t depth out = (
	if t == undefined or depth > 8 do return out
	local fname = ""
	if hasProperty t #filename do fname = t.filename
	if hasProperty t #fileName and fname == "" do fname = t.fileName
	append out ("{\"name\":" + jstr t.name + ",\"class\":" + jstr (classof t) + ",\"file\":" + jstr fname + ",\"exists\":" + (if fname == "" then "null" else (doesFileExist fname) as string) + "}")
	for i = 1 to getNumSubTexmaps t do texList (getSubTexmap t i) (depth+1) out
	out
)

fn mtlJson m depth = (
	local s = "{\"name\":" + jstr m.name + ",\"class\":" + jstr (classof m)
	local texs = #()
	for i = 1 to getNumSubTexmaps m do (
		local t = getSubTexmap m i
		if t != undefined do (
			local slot = getSubTexmapSlotName m i
			local a = texList t 0 #()
			local r = ""
			for j = 1 to a.count do r += (if j > 1 then "," else "") + a[j]
			append texs ("{\"slot\":" + jstr slot + ",\"maps\":[" + r + "]}")
		)
	)
	s += ",\"texmaps\":["
	for j = 1 to texs.count do s += (if j > 1 then "," else "") + texs[j]
	s += "]"
	-- a few common colour props
	for p in #(#color, #basecolor, #diffuse, #colorDiffuse, #levelDiffuse, #reflectionGlossiness, #baseRoughness, #metalnessMode) do
		if hasProperty m p do s += ",\"" + (p as string) + "\":" + jstr (getProperty m p)
	if depth < 4 and getNumSubMtls m > 0 do (
		s += ",\"sub\":["
		local first = true
		for i = 1 to getNumSubMtls m do (
			local sm = getSubMtl m i
			if sm != undefined do (
				s += (if first then "" else ",") + mtlJson sm (depth+1)
				first = false
			)
		)
		s += "]"
	)
	s + "}"
)

fn main = (
local log = createFile (WORK + "dump_ref.log")
try (
	format "loading...\n" to:log
	loadMaxFile REF quiet:true useFileUnits:true
	format "loaded: % objects, % sceneMaterials\n" objects.count sceneMaterials.count to:log
	format "renderer: %\n" (classof renderers.current) to:log

	-- usage counts
	local useCount = Dictionary #string
	for o in objects where o.material != undefined do (
		local k = o.material.name
		useCount[k] = (if hasDictValue useCount k then useCount[k] else 0) + 1
	)

	local f = createFile (WORK + "ref_materials.json")
	format "[\n" to:f
	local lib = materialLibrary()
	local i = 0
	for m in sceneMaterials do (
		i += 1
		local n = if hasDictValue useCount m.name then useCount[m.name] else 0
		local js = mtlJson m 0
		js = (substring js 1 (js.count-1)) + ",\"objects\":" + (n as string) + "}"
		format "%%\n" (if i > 1 then "," else "") js to:f
		append lib m
	)
	format "]\n" to:f
	close f
	saveTempMaterialLibrary lib (WORK + "technogym_sandstone_ref.mat")
	format "saved lib with % materials\n" lib.count to:log
	-- missing assets
	local miss = 0
	for b in getClassInstances BitmapTexture where b.filename != "" and not doesFileExist b.filename do miss += 1
	format "missing bitmaps: %\n" miss to:log
	format "DONE\n" to:log
) catch (
	format "ERROR: %\n" (getCurrentException()) to:log
)
close log
)
main()
