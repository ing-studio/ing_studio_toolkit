"""A set of streets as centre lines with stations: position, half width, centre height; and the street surface.

Heights are measured to the centre lines themselves (their segments), not to the nearest station: a point's station
and centre height are interpolated along the nearest segment, so a surface is continuous along a street. Where
streets meet, a point is near several centre lines: its height blends each street's own surface, weighted by
exp(-(distance - smallest distance) / blend_m), so junctions are smooth too; away from junctions only the street's own
centre line counts. Streets side by side at clearly different levels (a slip road beside a highway, split
carriageways on a slope) are not blended: the slope between them would be steeper than STEP_SLOPE, so they keep a
step (a wall) where their areas meet. Carriageway surface = centre height - cross fall x distance from the centre (crowned, falling to
both kerbs; beyond the edge it stays at the edge height). The centre lines' corners (a polyline through stations) are
rounded first (corner cutting), else a point inside a bend would jump between the stations of the two segments."""
import numpy as np
from shapely import STRtree, linestrings, points

STEP_SLOPE = 0.25  # steeper than this between two streets' centre lines: a step, not a slope


def rounded(v, times=3):
    """Corner cutting (Chaikin) of an open polyline of rows (x, y, ...): every corner cut `times` over, the end
    points kept; the other columns (height, half width) are cut the same way."""
    for _ in range(times):
        if len(v) < 3:
            return v
        q = 0.75 * v[:-1] + 0.25 * v[1:]
        r = 0.25 * v[:-1] + 0.75 * v[1:]
        mid = np.empty((2 * len(q), v.shape[1]))
        mid[0::2], mid[1::2] = q, r
        v = np.vstack([v[:1], mid[1:-1], v[-1:]])
    return v


class RoadNet:
    def __init__(self, edges, area, crossfall, blend_m=1.0):
        """edges: list of dict(xy (N, 2), s (N), half_w (N), z (N), ...); area: shapely carriageway area."""
        self.edges = [e for e in edges if len(e["xy"]) >= 2]
        self.area = area
        self.crossfall = float(crossfall)
        self.blend = float(blend_m)
        a, b, s0, s1, z0, z1, h0, h1, k = [], [], [], [], [], [], [], [], []
        for i, e in enumerate(self.edges):
            xy, s, z, hw = (np.asarray(e[key], dtype=np.float64) for key in ("xy", "s", "z", "half_w"))
            keep = np.r_[np.hypot(*np.diff(xy, axis=0).T) > 1e-9, True]  # no zero-length segments
            xy, s, z, hw = xy[keep], s[keep], z[keep], hw[keep]
            if len(xy) < 2:
                continue
            v = rounded(np.column_stack([xy, s, z, hw]))
            xy, s, z, hw = v[:, :2], v[:, 2], v[:, 3], v[:, 4]
            a.append(xy[:-1])
            b.append(xy[1:])
            s0.append(s[:-1])
            s1.append(s[1:])
            z0.append(z[:-1])
            z1.append(z[1:])
            h0.append(hw[:-1])
            h1.append(hw[1:])
            k.append(np.full(len(xy) - 1, i))
        if a:
            self.A, self.B = np.vstack(a), np.vstack(b)
            self.S0, self.S1 = np.concatenate(s0), np.concatenate(s1)
            self.Z0, self.Z1 = np.concatenate(z0), np.concatenate(z1)
            self.H0, self.H1 = np.concatenate(h0), np.concatenate(h1)
            self.K = np.concatenate(k)
            self.tree = STRtree(linestrings(np.stack([self.A, self.B], axis=1)))
        else:
            self.tree = None

    def _on(self, seg, xy):
        """Projection of points onto given segments: (distance, station, centre height, half width, side)."""
        A, B = self.A[seg], self.B[seg]
        AB = B - A
        t = np.clip(((xy - A) * AB).sum(axis=1) / np.maximum((AB ** 2).sum(axis=1), 1e-18), 0.0, 1.0)
        d = np.hypot(*(xy - (A + AB * t[:, None])).T)
        cross = AB[:, 0] * (xy[:, 1] - A[:, 1]) - AB[:, 1] * (xy[:, 0] - A[:, 0])
        return (d, self.S0[seg] + t * (self.S1[seg] - self.S0[seg]), self.Z0[seg] + t * (self.Z1[seg] - self.Z0[seg]),
                self.H0[seg] + t * (self.H1[seg] - self.H0[seg]), np.where(cross >= 0, 1.0, -1.0))

    def project(self, xy):
        """For each point, the nearest point of the centre lines: dict(edge, s, d (distance), side (+1 left, -1
        right), z (centre height there), hw (half width there))."""
        xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        (inp, hit), _ = self.tree.query_nearest(points(xy), return_distance=True, all_matches=False)
        seg = np.empty(len(xy), np.int64)
        seg[inp] = hit
        d, s, z, hw, side = self._on(seg, xy)
        return {"edge": self.K[seg], "s": s, "d": d, "side": side, "z": z, "hw": hw}

    def blended(self, xy, fn):
        """fn(centre height, distance, half width) of every street near each point, blended (see the module note)."""
        xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        if not len(xy):
            return np.zeros(0)
        near = self.project(xy)
        if self.blend <= 0:
            return fn(near["z"], near["d"], near["hw"])
        reach = near["d"] + 6.0 * self.blend
        inp, seg = self.tree.query(points(xy), predicate="dwithin", distance=reach)
        d, _, z, hw, _ = self._on(seg, xy[inp])
        # each street once per point: its nearest segment
        edge = self.K[seg]
        order = np.lexsort((d, edge, inp))
        inp, edge, d, z, hw = inp[order], edge[order], d[order], z[order], hw[order]
        first = np.r_[True, (inp[1:] != inp[:-1]) | (edge[1:] != edge[:-1])]
        inp, d, z, hw = inp[first], d[first], z[first], hw[first]
        w = np.exp(-(d - near["d"][inp]) / self.blend)
        w[np.abs(z - near["z"][inp]) > STEP_SLOPE * (d + near["d"][inp]) + 0.05] = 0.0  # another level: no blend
        w[d <= near["d"][inp]] = 1.0  # the nearest street itself
        num = np.bincount(inp, w * fn(z, d, hw), minlength=len(xy))
        den = np.bincount(inp, w, minlength=len(xy))
        return num / np.maximum(den, 1e-12)

    def surface_z(self, xy):
        """Carriageway surface height at points (the crown falls to the edges; beyond the edge it stays level)."""
        cf = self.crossfall
        return self.blended(xy, lambda z, d, hw: z - cf * np.minimum(d, hw))

    def to_json(self):
        return [{k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in e.items()} for e in self.edges]

    @classmethod
    def from_json(cls, edges, area, crossfall, blend_m=1.0):
        es = [{k: (np.asarray(v) if isinstance(v, list) and k in ("xy", "s", "half_w", "z", "ground", "grade", "limit",
                                                                      "radius") else v) for k, v in e.items()} for e in edges]
        return cls(es, area, crossfall, blend_m)
