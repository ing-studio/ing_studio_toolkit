-- A material board: every Sand Stone material on a rounded sample (a box with a cylinder and a sphere on it, 300 mm),
-- lit like a showroom and rendered with Corona, to check colours, texture sizes and bump before a long run.
-- Run by corona_materials.bat, which defines:
--   ING_WORK      the work folder: sandstone_materials.tsv; board.log
--   ING_MAPS      the folder of the maps (ends with \)
--   ING_BOARD     the image to write (.png)
--   ING_PASSES    Corona passes (e.g. 40)
--   ING_WIDTH     image width in pixels
if ING_WORK == undefined or ING_MAPS == undefined or ING_BOARD == undefined do throw "run this script with corona_materials.bat (it sets the paths)"
fileIn (getFilenamePath (getSourceFileName()) + "sandstone_materials.ms")
global LOGF
fn lg s = (format "% %\n" (localTime) s to:LOGF; flush LOGF)

fn boardMain = (
	LOGF = createFile (ING_WORK + "board.log")
	try (
		resetMaxFile #noPrompt
		units.SystemType = #millimeters
		SS_MAPS = ING_MAPS
		lg ("materials: " + (ssLoadSpecs (ING_WORK + "sandstone_materials.tsv")) as string)
		local names = for k in SS_SPECS.keys collect k
		sort names
		local cols = 5
		local step = 420.0
		local i = 0
		for nm in names do (
			local x = (mod i cols) * step
			local y = -(floor (i / cols)) * step * 1.5
			local m = ssMaterialFor nm undefined
			local b = ChamferBox length:300 width:300 height:120 Fillet:12 Fillet_Segments:4 pos:[x, y, 0]
			local c = Cylinder radius:70 height:160 sides:48 pos:[x - 60, y + 50, 120]
			local s = Sphere radius:60 segs:48 pos:[x + 75, y - 60, 180]
			for o in #(b, c, s) do o.material = m
			-- the name, printed on the floor in front of the sample
			local t = Text text:(substituteString (substituteString nm "SS_" "") "_" " ") size:28 pos:[x - 150, y - 190, 0.5]
			t.alignment = 1
			t.render_renderable = true
			t.render_displayRenderMesh = true
			t.render_thickness = 1.2
			t.material = ssMaterial "SS_Espresso_Rubber"
			i += 1
		)
		-- floor, light, camera
		local rows = ceil (names.count / (cols as float))
		local floor_ = Plane length:20000 width:20000 pos:[(cols - 1) * step / 2, -(rows - 1) * step * 1.5 / 2, 0]
		local fm = CoronaPhysicalMtl baseColor:(color 214 210 202) baseRoughness:0.6
		fm.name = "board floor"
		floor_.material = fm
		ssShowroomLight 50 -60
		local ctr = [(cols - 1) * step / 2, -(rows - 1) * step * 1.5 / 2, 120]
		local dist = (amax #(cols * step, rows * step * 1.5)) / (2 * tan 15) * 1.2   -- the whole board in view
		local cam = ssCamera (ctr + [0.12, -1.0, 1.5] * (dist / (length [0.12, -1.0, 1.5]))) ctr 30
		local r = CoronaRenderer()
		renderers.current = r
		r.progressive_passLimit = ING_PASSES
		r.denoise_filterType = 2
		ssSetExposure r -3.5
		renderWidth = ING_WIDTH
		renderHeight = (ING_WIDTH * 0.75) as integer
		lg "rendering..."
		render camera:cam outputfile:ING_BOARD vfb:false quiet:true
		lg ("saved " + ING_BOARD)
		saveMaxFile (ING_WORK + "material_board.max") quiet:true
		lg "DONE"
	) catch (
		lg ("ERROR: " + getCurrentException())
	)
	close LOGF
)
boardMain()
