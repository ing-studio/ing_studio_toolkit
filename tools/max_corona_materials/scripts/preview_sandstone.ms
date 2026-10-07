-- Step "preview" of the Sand Stone finish: Corona renders of a re-finished scene, to look at before using it. The scene
-- is only read: a floor, a showroom light (soft sun and sky) and cameras are added for the renders, never saved.
-- Run by corona_materials.bat, which defines:
--   ING_SCENE      the re-finished scene (.max)
--   ING_PREVIEW    the image prefix: <prefix>_overview.jpg, <prefix>_<equipment>.jpg
--   ING_CLOSEUPS   a text file: one equipment name per line (rendered alone, close up); may be missing
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
		-- the whole scene
		local cam = frameBox bb 40 1.6
		render camera:cam outputwidth:ING_WIDTH outputheight:((ING_WIDTH / 1.6) as integer) outputfile:(ING_PREVIEW + "_overview.jpg") vfb:false quiet:true
		lg ("saved " + ING_PREVIEW + "_overview.jpg")
		delete cam
		-- close-ups: each named equipment alone
		local names = if ING_CLOSEUPS != undefined and doesFileExist ING_CLOSEUPS then filterString ((dotNetClass "System.IO.File").ReadAllText ING_CLOSEUPS) "\r\n" else #()
		for nm in names do (
			local E = getNodeByName nm
			if not isValidNode E do (lg ("not in the scene: " + nm); continue)
			local mine = for o in allDescendants E where superclassof o == GeometryClass collect o
			hide geo
			unhide mine
			local eb = boxOf mine
			fl.pos.z = eb[1].z - 1
			local c = frameBox eb 32 1.0
			local out = ING_PREVIEW + "_" + safeName nm + ".jpg"
			render camera:c outputwidth:(ING_WIDTH * 0.75) outputheight:(ING_WIDTH * 0.75) outputfile:out vfb:false quiet:true
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
