-- Step "preview" of the Sand Stone finish: Corona renders of a re-finished scene, to look at before using it. The scene
-- is only read: a floor, a showroom light (soft sun and sky) and cameras are added for the renders, never saved.
-- Run by corona_materials.bat, which defines:
--   ING_SCENE      the re-finished scene (.max)
--   ING_PREVIEW    the folder of the images (ends with \)
--   ING_VIEWS      a text file: one image per line, its name \t the node to show (alone, with everything under it):
--                  a scene's dummy (all its equipment; wide) or one equipment (close up; square)
--   ING_PASSES     Corona passes per image
--   ING_WIDTH      image width in pixels
--   ING_LOG        the log to write; its last line is DONE or ERROR: ...
if ING_SCENE == undefined or ING_PREVIEW == undefined do throw "run this script with corona_materials.bat (it sets the paths)"
fileIn (getFilenamePath (getSourceFileName()) + "sandstone_materials.ms")
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
fn boxOf nodes = (
	local bmin = [1e12,1e12,1e12]; local bmax = [-1e12,-1e12,-1e12]
	for o in nodes where superclassof o == GeometryClass and not o.isHidden do (
		bmin = [amin bmin.x o.min.x, amin bmin.y o.min.y, amin bmin.z o.min.z]
		bmax = [amax bmax.x o.max.x, amax bmax.y o.max.y, amax bmax.z o.max.z]
	)
	#(bmin, bmax)
)
fn safeName s = (
	local r = ""
	for i = 1 to s.count do r += (if findString "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" s[i] != undefined then s[i] else "_")
	r
)
-- a camera from the front-left, a little above, framing the box
fn frameBox bb fovDeg aspect = (
	local ctr = (bb[1] + bb[2]) / 2
	local size = bb[2] - bb[1]
	local rad = (length size) / 2
	local dir = normalize [0.75, 1.0, -0.55]   -- the view direction: from the front-left, looking down a little
	local dist = rad / (tan (fovDeg / 2)) * (if aspect > 1 then 1.0 else 1.25) * 1.08
	ssCamera (ctr - dir * dist) ctr fovDeg
)

fn previewMain = (
	LOGF = createFile ING_LOG
	try (
		loadMaxFile ING_SCENE quiet:true useFileUnits:true
		lg ("loaded " + ING_SCENE + ": " + objects.count as string + " objects")
		local geo = for o in objects where superclassof o == GeometryClass collect o
		local bb = boxOf geo
		local floorMtl = CoronaPhysicalMtl baseColor:(color 140 135 127) baseRoughness:0.55
		floorMtl.name = "preview floor"
		local span = amax #(bb[2].x - bb[1].x, bb[2].y - bb[1].y, 2000)
		local fl = Plane length:(span * 6) width:(span * 6) pos:[(bb[1].x + bb[2].x) / 2, (bb[1].y + bb[2].y) / 2, bb[1].z - 1]
		fl.material = floorMtl
		ssShowroomLight 48 -55
		local r = CoronaRenderer()
		renderers.current = r
		r.progressive_passLimit = ING_PASSES
		r.denoise_filterType = 2
		ssSetExposure r -4.0
		local views = if ING_VIEWS != undefined and doesFileExist ING_VIEWS then filterString ((dotNetClass "System.IO.File").ReadAllText ING_VIEWS) "\r\n" else #()
		for v in views do (
			local f = filterString v "\t"
			if f.count < 2 do continue
			local N = getNodeByName f[2] exact:true
			if not isValidNode N do (lg ("not in the scene: " + f[2]); continue)
			local mine = for o in allDescendants N where superclassof o == GeometryClass collect o
			if mine.count == 0 do continue
			hide geo
			unhide mine
			local eb = boxOf mine
			fl.pos.z = eb[1].z - 1
			-- a scene's dummy (at the top of the scene): all its equipment, wide; one equipment: close up, square
			local wide = N.parent == undefined
			local w = (if wide then ING_WIDTH else ING_WIDTH * 0.75) as integer
			local h = (if wide then ING_WIDTH / 1.6 else ING_WIDTH * 0.75) as integer
			local c = frameBox eb (if wide then 40 else 32) (w as float / h)
			local out = ING_PREVIEW + safeName f[1] + ".jpg"
			render camera:c outputwidth:w outputheight:h outputfile:out vfb:false quiet:true
			delete c
			lg ("saved " + out)
		)
		unhide geo
		lg "DONE"
	) catch (
		lg ("ERROR: " + getCurrentException())
	)
	close LOGF
)
previewMain()
