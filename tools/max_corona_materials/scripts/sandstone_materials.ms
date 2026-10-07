-- The Sand Stone materials as Corona Physical materials, from sandstone_materials.tsv (written by
-- corona_materials/sandstone.py). fileIn'd by refinish_sandstone.ms and material_board.ms; defines:
--   SS_SPECS                  name -> the row's fields (a Dictionary of strings)
--   ssLoadSpecs tsvPath       reads the tsv
--   ssMaterial name           the material (one instance per name)
--   ssMaterialFor name srcMtl the material for a source material: logos and displays get their own instance, which
--                             keeps the source's image and its mapping (the print and the plate are Sand Stone colours)
-- The maps are in SS_MAPS (a folder ending with \); every texture is mapped triplanar in object space, tile_mm wide,
-- so it needs no UVs and keeps its real size on every object.
global SS_SPECS, SS_MAPS, SS_CACHE, SS_SRC_CACHE
global SS_FIELDS = #("name", "kind", "metal", "rgb", "albedo", "rough", "rough_map", "bump_map", "bump", "tile_mm", "ior", "coat", "coat_rough", "sheen", "sheen_rgb", "sheen_rough", "round_mm", "glow", "print_rgb", "chamfer_mm")

-- colours in the tsv are linear 0..255 (3ds Max's colour management reads colour values as linear)
fn ssColor s = (local a = filterString s ","; color (a[1] as float) (a[2] as float) (a[3] as float))
fn ssNum spec k dflt = (local v = spec[k]; if v == undefined or v == "" then dflt else v as float)

fn ssLoadSpecs tsvPath = (
	SS_SPECS = Dictionary #string
	SS_CACHE = Dictionary #string
	SS_SRC_CACHE = Dictionary #string
	local lines = filterString ((dotNetClass "System.IO.File").ReadAllText tsvPath) "\r\n"
	for line in lines do (
		local f = filterString line "\t" splitEmptyTokens:true
		local d = Dictionary #string
		for i = 1 to SS_FIELDS.count do d[SS_FIELDS[i]] = (if i <= f.count then f[i] else "")
		SS_SPECS[d["name"]] = d
	)
	SS_SPECS.count
)

-- a map of the Sand Stone set, triplanar in object space; colour maps are sRGB, the others linear
fn ssTex mapName tileMM isColour = (
	local b = CoronaBitmap()
	b.filename = SS_MAPS + mapName + ".png"
	-- colour maps are sRGB; roughness and height are data, read as they are
	b.useLegacyGamma = true
	b.gamma = if isColour then 2.2 else 1.0
	local t = CoronaTriplanar()
	t.texmapX = b
	t.onlyTexmapX = true
	t.space = 0
	t.scale = tileMM
	t.Blend = 0.3
	t.name = mapName
	t
)

fn ssBuild spec = (
	local m = CoronaPhysicalMtl()
	m.name = spec["name"]
	m.roughnessMode = 0
	m.metalnessMode = (if spec["metal"] == "1" then 1 else 0)
	m.baseColor = ssColor spec["rgb"]
	m.baseRoughness = ssNum spec "rough" 0.5
	m.baseIor = ssNum spec "ior" 1.5
	local tile = ssNum spec "tile_mm" 100.0
	if spec["albedo"] != "" do (m.baseTexmap = ssTex spec["albedo"] tile true; m.baseMapAmount = 100.0)
	if spec["rough_map"] != "" do (m.baseRoughnessTexmap = ssTex spec["rough_map"] tile false; m.baseRoughnessMapAmount = 100.0)
	local coat = ssNum spec "coat" 0.0
	if coat > 0 do (m.clearcoatAmount = coat; m.clearcoatRoughness = ssNum spec "coat_rough" 0.1; m.clearcoatIor = 1.5)
	local sheen = ssNum spec "sheen" 0.0
	if sheen > 0 do (m.sheenAmount = sheen; m.sheenColor = ssColor spec["sheen_rgb"]; m.sheenRoughness = ssNum spec "sheen_rough" 0.4)
	-- bump: the finish's texture, inside Corona Round Edges (soft, real edges instead of CAD-sharp ones)
	local bumpTex = if spec["bump_map"] != "" then ssTex spec["bump_map"] tile false else undefined
	local r = ssNum spec "round_mm" 0.0
	if r > 0 then (
		local re = CoronaRoundEdges()
		re.radius = r
		re.Samples = 10
		-- the Precise mode: it also rounds where two objects or two parts of a mesh meet (a tube into a frame, a bar
		-- into its bracket), so joints read as one welded or moulded piece; the Fast mode leaves those creases sharp and
		-- streaks flat panels around their long thin triangles
		re.algorithm = 1
		if bumpTex != undefined do (re.mapAdditionalBump = bumpTex; re.mapStrengthAdditional = ssNum spec "bump" 0.1)
		m.baseBumpTexmap = re
		m.baseBumpMapAmount = 1.0
	) else if bumpTex != undefined do (
		m.baseBumpTexmap = bumpTex
		m.baseBumpMapAmount = ssNum spec "bump" 0.1
	)
	m
)

fn ssMaterial name = (
	if hasDictValue SS_CACHE name do return SS_CACHE[name]
	if not hasDictValue SS_SPECS name do throw ("no Sand Stone material " + name)
	local m = ssBuild SS_SPECS[name]
	SS_CACHE[name] = m
	m
)

-- the first bitmap (file) map anywhere in a material's maps
fn ssFindBitmap t depth = (
	if t == undefined or depth > 8 do return undefined
	if (classof t == BitmapTexture or classof t == CoronaBitmap) and t.filename != undefined and t.filename != "" do return t
	for i = 1 to getNumSubTexmaps t do (
		local r = ssFindBitmap (getSubTexmap t i) (depth + 1)
		if r != undefined do return r
	)
	undefined
)

-- a copy of the source's image map, pointed at the copy in SS_MAPS when there is one
fn ssSourceImage srcMtl = (
	if srcMtl == undefined do return undefined
	local b = ssFindBitmap srcMtl 0
	if b == undefined do return undefined
	b = copy b
	local local_ = SS_MAPS + (filenameFromPath b.filename)
	if doesFileExist local_ do b.filename = local_
	b
)

fn ssMaterialFor name srcMtl = (
	local spec = SS_SPECS[name]
	if spec == undefined do throw ("no Sand Stone material " + name)
	if spec["kind"] == "plain" do return ssMaterial name
	local key = name + "|" + (if srcMtl == undefined then "" else srcMtl.name)
	if hasDictValue SS_SRC_CACHE key do return SS_SRC_CACHE[key]
	local m = ssBuild spec
	local img = ssSourceImage srcMtl
	if img != undefined do (
		if spec["kind"] == "logo" then (
			-- the logo image is black print on white: print where it is dark, plate where it is light
			local mx = Mix()
			mx.color1 = ssColor spec["print_rgb"]
			mx.color2 = ssColor spec["rgb"]
			mx.mask = img
			m.baseTexmap = mx
			m.baseMapAmount = 100.0
		) else if spec["kind"] == "display" do (
			m.selfIllumTexmap = img
			m.selfIllumLevel = ssNum spec "glow" 1.0
		)
	)
	m.name = name + " - " + (if srcMtl == undefined then "" else srcMtl.name)
	SS_SRC_CACHE[key] = m
	m
)

-- the exposure (EV) of Corona's colour mapping: its Simple Exposure operator
fn ssSetExposure r ev = (
	local op = r.colorMap_pipeline
	while op != undefined do (
		if classof op == SimpleExposureOperatorPlugin do op.colorMappingOperator_simpleExposure = ev
		op = try (op.colorMappingOperator_nextOperator) catch undefined
	)
)

-- a showroom light: a big soft sun (its +Z points at it) and a hazy sky; ssSetExposure -4 suits it
fn ssShowroomLight elevationDeg azimuthDeg = (
	local sun = CoronaSun()
	sun.targeted = false
	local el = elevationDeg; local az = azimuthDeg
	sun.dir = normalize [(cos el) * (cos az), (cos el) * (sin az), sin el]
	sun.pos = sun.dir * 100000
	sun.intensity = 1.0
	sun.sizeMultiplier = 6.0            -- a big sun: soft shadows, like a bright hazy day through windows
	local sky = CoronaSky()
	sky.turbidity = 7.0                 -- hazy: a whiter sky, no blue shadows
	environmentMap = sky
	sun
)

-- a camera at eye looking at target, upright
fn ssCamera eye target fovDeg = (
	local tgt = Targetobject pos:target
	Targetcamera pos:eye target:tgt fov:fovDeg
)
