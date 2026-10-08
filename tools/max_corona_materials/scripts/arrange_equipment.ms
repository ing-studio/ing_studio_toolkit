-- The equipment of a scene arranged in rows. fileIn'd by refinish_sandstone.ms; defines
--   eqBox E                       the box of an equipment's geometry, #(min, max), or undefined when it has none
--   arrangeEquipment eqs gap      the equipment in rows from the origin -> #(how many, width, depth)
fn aeDescendants root = (
	local out = #(); local stack = #(root)
	while stack.count > 0 do (
		local c = stack[stack.count]; deleteItem stack stack.count
		append out c
		for ch in c.children do append stack ch
	)
	out
)
-- the box of an equipment's geometry (#(min, max)), or undefined when it has none
fn eqBox E = (
	local bmin = [1e12, 1e12, 1e12]; local bmax = [-1e12, -1e12, -1e12]; local n = 0
	for o in aeDescendants E where superclassof o == GeometryClass do (
		n += 1
		bmin = [amin bmin.x o.min.x, amin bmin.y o.min.y, amin bmin.z o.min.z]
		bmax = [amax bmax.x o.max.x, amax bmax.y o.max.y, amax bmax.z o.max.z]
	)
	if n == 0 then undefined else #(bmin, bmax)
)
-- the equipment in rows from the origin, along +X, the rows towards -Y (the deepest first: the big machines at the
-- back, the small things in front), gap apart, standing on the floor (z = 0); a row is as long as the whole would be
-- wide arranged in a rectangle of about 1.6 : 1. Near the origin the scene's numbers keep their precision (the
-- import's equipment lay up to 400 m away), and the combine step can put the scenes side by side. Returns
-- #(the equipment arranged, width, depth)
fn aeByDepth a b = (
	local da = a[3].y - a[2].y; local db = b[3].y - b[2].y
	if da > db + 1 then -1 else if db > da + 1 then 1 else (
		local wa = a[3].x - a[2].x; local wb = b[3].x - b[2].x
		if wa > wb then -1 else if wb > wa then 1 else 0
	)
)
fn arrangeEquipment eqs gap = (
	local items = #()
	for E in eqs where isValidNode E do (local b = eqBox E; if b != undefined do append items #(E, b[1], b[2]))
	qsort items aeByDepth
	local area = 0.0; local widest = 0.0
	for it in items do (local d = it[3] - it[2]; area += (d.x + gap) * (d.y + gap); widest = amax widest d.x)
	local rowW = amax widest (sqrt (1.6 * area))
	local x = 0.0; local y = 0.0; local rowD = 0.0; local w = 0.0
	for it in items do (
		local d = it[3] - it[2]
		if x > 0 and x + d.x > rowW do (y -= rowD + gap; x = 0.0; rowD = 0.0)
		move it[1] [x - it[2].x, y - it[3].y, -it[2].z]
		w = amax w (x + d.x)
		x += d.x + gap
		rowD = amax rowD d.y
	)
	#(items.count, w, -y + rowD)
)
