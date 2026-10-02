-- Step "rebuild": the imported model rebuilt as clean parts:
--   one Max group per equipment, one Editable Mesh per part material inside it,
--   one Corona material per part type, one layer per part type, duplicate (overlapping) meshes removed.
-- Run by max_materials.bat, which defines:
--   ING_WORK         the work folder: reference.mat, part_materials.tsv, part_map.tsv; the logs and reports go here
--   ING_RAW          the raw import (.max) of the model
--   ING_OUT          the result to write (.max)
--   ING_MODEL_ROOT   the node the equipment groups are under (missing: the scene's top-level nodes are the groups)
--   ING_FALLBACK     the part of a mesh whose material is in no map
-- Set TEST_GROUPS > 0 to process only that many groups and save to the work folder (restructure_test.max).
if ING_WORK == undefined or ING_RAW == undefined or ING_OUT == undefined do throw "run this script with max_materials.bat (it sets the paths)"
if TEST_GROUPS == undefined do global TEST_GROUPS = 0
global OUT = if TEST_GROUPS > 0 then (ING_WORK + "restructure_test.max") else ING_OUT
global LOGF

fn lg s = (format "% %\n" (localTime) s to:LOGF; flush LOGF)

fn normKey s = (
	local r = ""
	for i = 1 to s.count do (
		local c = toLower s[i]
		if findString "abcdefghijklmnopqrstuvwxyz0123456789" c != undefined do r += c
	)
	r
)

fn chainMissing t depth = (
	if t == undefined or depth > 10 do return false
	if hasProperty t #filename and t.filename != undefined and t.filename != "" and not doesFileExist t.filename do return true
	for i = 1 to getNumSubTexmaps t do if chainMissing (getSubTexmap t i) (depth+1) do return true
	false
)

fn disableMissingSlots m = (
	for p in getPropNames m do (
		local ps = p as string
		if matchPattern ps pattern:"texmap*" and not matchPattern ps pattern:"texmapOn*" do (
			local t = getProperty m p
			if superclassof t == textureMap and chainMissing t 0 do (
				local onp = ("texmapOn" + substring ps 7 -1) as name
				if hasProperty m onp do setProperty m onp false
			)
		)
	)
)

fn parseColor s = (local a = filterString s ","; color (a[1] as integer) (a[2] as integer) (a[3] as integer))

fn readLines path = filterString ((dotNetClass "System.IO.File").ReadAllText path) "\r\n"

fn r1 v = ((floor (v * 10 + 0.5)) as integer) as string

-- source material preference when two coincident meshes carry different materials
fn srcRank nm = (
	if matchPattern nm pattern:"TG*" then 3
	else if matchPattern nm pattern:"_auto_*" or matchPattern nm pattern:"Material__*" or matchPattern nm pattern:"material__*" then 1
	else 2
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

fn main = (
	LOGF = createFile (ING_WORK + (if TEST_GROUPS > 0 then "restructure_test.log" else "restructure.log"))
	try (
		------------------------------------------------------------ part materials
		local lib = loadTempMaterialLibrary (ING_WORK + "reference.mat")
		local tmpl = Dictionary #string
		for i = 1 to lib.count do tmpl[lib[i].name] = lib[i]

		loadMaxFile ING_RAW quiet:true
		lg ("loaded raw import: " + objects.count as string + " objects")

		local partMtl = Dictionary #string
		local partLayer = Dictionary #string
		for line in readLines (ING_WORK + "part_materials.tsv") do (
			local f = filterString line "\t" splitEmptyTokens:true
			local m = copy tmpl[f[2]]
			m.name = f[1]
			disableMissingSlots m
			if f[3] != "" do m.colorDiffuse = parseColor f[3]
			if f[4] != "" do m.reflectGlossiness = f[4] as float
			if f[5] != "" do m.fresnelIor = f[5] as float
			partMtl[f[1]] = m
			local lay = LayerManager.getLayerFromName f[1]
			if lay == undefined do lay = LayerManager.newLayerFromName f[1]
			partLayer[f[1]] = lay
		)
		lg ("part materials: " + partMtl.count as string)

		local srcToPart = Dictionary #string
		for line in readLines (ING_WORK + "part_map.tsv") do (
			local f = filterString line "\t"
			srcToPart[normKey f[1]] = f[2]
		)

		fn partOf srcToPart mtl = (
			if mtl == undefined do return ING_FALLBACK
			local k = normKey mtl.name
			if hasDictValue srcToPart k do return srcToPart[k]
			while k.count > 0 and findString "0123456789" k[k.count] != undefined do k = substring k 1 (k.count-1)
			if hasDictValue srcToPart k then srcToPart[k] else ING_FALLBACK
		)

		------------------------------------------------------------ per equipment group
		local root = getNodeByName ING_MODEL_ROOT
		local groupsIn = if isValidNode root then (for c in root.children collect c) else (for o in objects where o.parent == undefined collect o)
		lg ("equipment groups: " + groupsIn.count as string + (if isValidNode root then (" under " + ING_MODEL_ROOT) else " (top-level nodes)"))
		if TEST_GROUPS > 0 do (
			-- test on a mix: first groups plus the ones with multi-materials / duplicates
			local pick = #()
			for i = 1 to amin TEST_GROUPS groupsIn.count do append pick groupsIn[i]
			groupsIn = pick
		)
		local seenGeo = Dictionary #string        -- global duplicate key -> #(rank, groupName)
		local rep = createFile (ING_WORK + (if TEST_GROUPS > 0 then "parts_test.tsv" else "parts.tsv"))
		local dupLog = createFile (ING_WORK + (if TEST_GROUPS > 0 then "duplicates_test.tsv" else "duplicates.tsv"))
		local nGroups = 0; local nParts = 0; local nDupSame = 0; local nDupDiff = 0; local nSplit = 0; local nEmpty = 0
		local gi = 0
		for G in groupsIn do (
			gi += 1
			local gname = G.name
			local desc = allDescendants G
			local geos = for o in desc where superclassof o == GeometryClass and canConvertTo o TriMeshGeometry collect o

			-- 1) pieces = #(trimesh, part, sourceName, key)
			local pieces = #()
			for o in geos do (
				local tm = snapshotAsMesh o
				if tm.numfaces == 0 do continue
				local key = (tm.numfaces as string) + "|" + r1 o.min.x + "," + r1 o.min.y + "," + r1 o.min.z + "|" + r1 o.max.x + "," + r1 o.max.y + "," + r1 o.max.z
				local mt = o.material
				if classof mt == MultiMaterial then (
					local ids = #()
					for fi = 1 to tm.numfaces do appendIfUnique ids (getFaceMatID tm fi)
					if ids.count > 1 do nSplit += 1
					for id in ids do (
						local idx = findItem mt.materialIDList id
						if idx == 0 do idx = (mod (id - 1) mt.numsubs) as integer + 1
						local sm = mt.materialList[idx]
						local faces = for fi = 1 to tm.numfaces where getFaceMatID tm fi == id collect fi
						local sub = if ids.count == 1 then tm else meshop.detachFaces tm faces delete:false asMesh:true
						append pieces #(sub, partOf srcToPart sm, (if sm == undefined then "" else sm.name), key + "|" + id as string)
					)
				) else (
					append pieces #(tm, partOf srcToPart mt, (if mt == undefined then "" else mt.name), key)
				)
			)

			-- 2) drop coincident duplicates (same face count + same world bbox), keep the better-named material
			local keep = #()
			local groupKeys = #()
			for p in pieces do (
				local k = p[4]
				local rk = srcRank p[3]
				if hasDictValue seenGeo k then (
					local prev = seenGeo[k]     -- #(pieceArrayOrUndefined, part, rank, src, group)
					if prev[2] == p[2] then (
						nDupSame += 1
						format "same\t%\t%\t%\t%\n" gname p[3] prev[5] prev[4] to:dupLog
					) else (
						nDupDiff += 1
						-- different materials on the same geometry: keep the higher-ranked one
						if rk > prev[3] and prev[1] != undefined then (
							local ix = findItem keep prev[1]
							if ix > 0 do keep[ix] = p
							format "diff\tkept %\tdropped %\t%\t%\n" p[3] prev[4] gname prev[5] to:dupLog
							seenGeo[k] = #(p, p[2], rk, p[3], gname)
							append groupKeys k
						) else (
							format "diff\tkept %\tdropped %\t%\t%\n" prev[4] p[3] gname prev[5] to:dupLog
						)
					)
				) else (
					append keep p
					append groupKeys k
					seenGeo[k] = #(p, p[2], rk, p[3], gname)
				)
			)

			-- 3) merge per part
			local merged = Dictionary #string
			for p in keep do (
				if hasDictValue merged p[2] then meshop.attach merged[p[2]] p[1]
				else merged[p[2]] = copy p[1]
			)

			-- 4) delete old nodes, build new part nodes, group them
			delete desc
			if merged.count == 0 then (nEmpty += 1) else (
				local parts = #()
				for pk in merged.keys do (
					local tm = merged[pk]
					local n = mesh mesh:tm
					n.name = gname + "__" + (substring pk 4 -1)
					n.material = partMtl[pk]
					n.pivot = n.center
					partLayer[pk].addNode n
					append parts n
					format "%\t%\t%\n" gname n.name tm.numfaces to:rep
				)
				local gh = group parts name:gname
				nGroups += 1; nParts += parts.count
			)
			-- the stored piece meshes for this group are no longer needed
			for k in groupKeys do (seenGeo[k])[1] = undefined
			if mod gi 10 == 0 do (lg ("groups " + gi as string + "/" + groupsIn.count as string + "  parts " + nParts as string); gc light:true)
		)
		close rep; close dupLog
		if isValidNode root and root.children.count == 0 do delete root
		lg ("groups built " + nGroups as string + ", parts " + nParts as string + ", empty groups removed " + nEmpty as string)
		lg ("multi-material meshes split " + nSplit as string + ", duplicates removed: same material " + nDupSame as string + ", different material " + nDupDiff as string)

		-- leftover check
		local stray = for o in objects where superclassof o == GeometryClass and (o.parent == undefined or not isGroupHead o.parent) collect o
		lg ("geometry outside part groups: " + stray.count as string)

		renderers.current = CoronaRenderer()
		if doesFileExist OUT do deleteFile OUT
		saveMaxFile OUT quiet:true
		lg ("saved " + OUT)
		lg "DONE"
	) catch (
		lg ("ERROR: " + getCurrentException())
	)
	close LOGF
)
main()
