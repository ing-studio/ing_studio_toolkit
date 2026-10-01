"""The numbering rules, without Archicad:  python -m unittest discover tests  (from the tool folder)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from uids import sheet  # noqa: E402
from uids.types import assign  # noqa: E402
from uids.util import load_config  # noqa: E402
from uids.windows import Window  # noqa: E402

CFG = load_config()


def win(n, w, h, floor=0, hand="", wid="", part="Window 27", x=0.0, y=0.0, sill=0.9, **params):
    return Window(guid=f"g{n}", id=wid, floor=floor, part=part, width=w, height=h, sill=sill, hand=hand,
                  params=params, x=x, y=y)


def labels(types):
    return {w.guid: t.label for t in types for w in t.windows}


class Numbering(unittest.TestCase):
    def test_same_size_same_type_sill_ignored(self):
        t = assign([win(1, 1.2, 1.5, sill=0.9), win(2, 1.2, 1.5, sill=1.2), win(3, 1.0, 1.5)], CFG)
        self.assertEqual(len(t), 2)
        self.assertEqual(labels(t)["g1"], labels(t)["g2"])

    def test_labels_armenian_two_digits(self):
        t = assign([win(1, 1.2, 1.5)], CFG)
        self.assertEqual(t[0].label, "Պ-01")

    def test_floor_order(self):
        t = assign([win(1, 1.0, 1.0, floor=2), win(2, 2.0, 1.0, floor=0, x=5), win(3, 3.0, 1.0, floor=0, x=1)], CFG)
        self.assertEqual([labels(t)[g] for g in ("g3", "g2", "g1")], ["Պ-01", "Պ-02", "Պ-03"])

    def test_other_hand_gets_prime_majority_plain(self):
        t = assign([win(1, 1.8, 1.8, hand="L"), win(2, 1.8, 1.8, hand="R"), win(3, 1.8, 1.8, hand="L")], CFG)
        lab = labels(t)
        self.assertEqual((lab["g1"], lab["g2"], lab["g3"]), ("Պ-01", "Պ-01'", "Պ-01"))

    def test_type_params_split(self):
        t = assign([win(1, 1.0, 2.0, vgn_01=3), win(2, 1.0, 2.0, vgn_01=4)], CFG)
        self.assertEqual(len(t), 2)

    def test_existing_numbers_kept_new_types_fill_free_numbers(self):
        ws = [win(1, 1.0, 1.0, wid="Պ-05"), win(2, 1.0, 1.0, wid="Պ-05"), win(3, 2.0, 1.0, wid="Պ-02"),
              win(4, 3.0, 1.0, wid="D-7", x=1), win(5, 4.0, 1.0, x=2), win(6, 5.0, 1.0, x=3), win(7, 6.0, 1.0, x=4)]
        lab = labels(assign(ws, CFG))
        self.assertEqual([lab[f"g{i}"] for i in range(1, 8)],
                         ["Պ-05", "Պ-05", "Պ-02", "Պ-01", "Պ-03", "Պ-04", "Պ-06"])

    def test_unwritten_ids_numbered_as_on_the_first_run(self):
        # first run: 3 types, the middle one on a locked layer keeps its old ID -> the second run gives it the same
        ws = [win(1, 1.0, 1.0, x=0), win(2, 2.0, 1.0, x=1), win(3, 3.0, 1.0, x=2)]
        first = labels(assign(ws, CFG))
        ws2 = [win(1, 1.0, 1.0, x=0, wid=first["g1"]), win(2, 2.0, 1.0, x=1, wid="WD - 003"),
               win(3, 3.0, 1.0, x=2, wid=first["g3"])]
        self.assertEqual(labels(assign(ws2, CFG)), first)

    def test_renumber_ignores_existing(self):
        ws = [win(1, 1.0, 1.0, wid="Պ-05", x=0), win(2, 2.0, 1.0, wid="Պ-02", x=5)]
        lab = labels(assign(ws, CFG, renumber=True))
        self.assertEqual((lab["g1"], lab["g2"]), ("Պ-01", "Պ-02"))

    def test_one_number_claimed_by_two_types(self):
        # someone gave Պ-03 to two different windows: the type with more votes keeps it, the other takes a free one
        ws = [win(1, 1.0, 1.0, wid="Պ-03"), win(2, 1.0, 1.0, wid="Պ-03"), win(3, 2.0, 1.0, wid="Պ-03")]
        lab = labels(assign(ws, CFG))
        self.assertEqual(lab["g1"], "Պ-03")
        self.assertEqual(lab["g3"], "Պ-01")

    def test_prime_side_kept_from_existing_ids(self):
        # R already carries the plain number, even though L now has more windows
        ws = [win(1, 1.8, 1.8, hand="R", wid="Պ-02"), win(2, 1.8, 1.8, hand="L", wid="Պ-02'"),
              win(3, 1.8, 1.8, hand="L", wid="Պ-02'")]
        lab = labels(assign(ws, CFG))
        self.assertEqual((lab["g1"], lab["g2"]), ("Պ-02", "Պ-02'"))

    def test_existing_id_with_one_digit_accepted(self):
        lab = labels(assign([win(1, 1.0, 1.0, wid="Պ-7")], CFG))
        self.assertEqual(lab["g1"], "Պ-07")


class Sheet(unittest.TestCase):
    def test_layout_has_a_dimension_pair_per_type_and_svg(self):
        ws = [win(1, 1.8, 1.8, part="2-Sash Sliding Window 27", hand="L"), win(2, 1.0, 3.0, floor=1)]
        types = assign(ws, CFG)
        d = sheet.layout(types, {0: "Հարկ 0", 1: "Հարկ 1"}, CFG)
        dims = [it for it in d.items if isinstance(it, sheet.Dim)]
        self.assertEqual(len(dims), 2 * len(types))
        self.assertIn("Պ-01", sheet.to_svg(d, CFG))

    def _sheet(self):
        ws = [win(1, 2.4, 1.8, part="3-Sash Sliding Window 27", sill=0.9),
              win(2, 2.4, 1.8, part="3-Sash Sliding Window 27", sill=1.2, floor=1), win(3, 1.0, 3.0),
              win(4, 0.8, 3.1, sill=0.35), win(5, 5.45, 2.4), win(6, 1.8, 1.8, hand="L"), win(7, 1.8, 1.8, hand="R"),
              win(8, 1.15, 3.1, floor=1)]
        types = assign(ws, CFG)
        return types, sheet.layout(types, {0: "Ground Floor", 1: "Հարկ 1 (+3.75)"}, CFG)

    def test_views_of_a_row_stand_on_one_line_under_their_marks_on_one_line(self):
        types, d = self._sheet()
        p = CFG["worksheet"]["scale"] / 1000
        labels = {t.label for t in types}
        marks = {it.text: it.at for it in d.items if isinstance(it, sheet.Text) and it.text in labels
                 and it.size == sheet.MARK_MM}
        outlines = {it.key: it.points for it in d.items if isinstance(it, sheet.Poly) and it.key}
        rows = {}
        for t in types:
            rows.setdefault(round(marks[t.label][1], 6), []).append(t.label)
        for row in rows.values():  # one mark line: one base line, every view centred under its mark
            self.assertEqual(len({round(min(y for _x, y in outlines[k]), 6) for k in row}), 1)
            for k in row:
                xs = [x for x, _y in outlines[k]]
                self.assertAlmostEqual((min(xs) + max(xs)) / 2, marks[k][0], places=6)
        lowest_view = min(y for pts in outlines.values() for _x, y in pts)
        under = [it for it in d.items if isinstance(it, sheet.Text) and it.size == sheet.TEXT_MM
                 and it.align == "Center" and it.at[1] > lowest_view - 0.6]  # the lines under the views
        for a in under:  # no two texts of one line overlap
            for b in under:
                if a is not b and abs(a.at[1] - b.at[1]) < 1e-9:
                    room = (sheet.text_mm(a.text, a.size) + sheet.text_mm(b.text, b.size)) / 2 * p
                    self.assertGreaterEqual(abs(a.at[0] - b.at[0]), room, (a.text, b.text))

    def test_every_table_text_fits_its_column(self):
        types, d = self._sheet()
        p = CFG["worksheet"]["scale"] / 1000
        lowest_view = min(y for it in d.items if isinstance(it, sheet.Poly) and it.key for _x, y in it.points)
        verticals = [it.points for it in d.items if isinstance(it, sheet.Poly) and not it.key
                     and len(it.points) == 2 and it.points[0][0] == it.points[1][0] and it.points[0][1] < lowest_view]
        cols = sorted({round(pts[0][0], 6) for pts in verticals})
        cells = [it for it in d.items if isinstance(it, sheet.Text) and it.size == sheet.TEXT_MM
                 and it.align == "Center" and it.at[1] < lowest_view and it.text != "Քանակ ըստ հարկերի"]
        self.assertGreater(len(cells), 20)
        for c in cells:
            left = max(x for x in cols if x <= c.at[0])
            right = min(x for x in cols if x > c.at[0])
            self.assertLessEqual(sheet.text_mm(c.text, c.size) * p, right - left, c.text)

    def test_opening_in_words(self):
        types, _d = self._sheet()
        by = {t.part: t for t in types}
        self.assertEqual(sheet.opening(by["3-Sash Sliding Window 27"]), "սահող")
        t = assign([Window(guid="x", id="", floor=0, part="Window 27", width=1, height=1, sill=0.9, hand="",
                           draw={"gs_optype_01": "Fixed Glass", "gs_optype_02": ""})], CFG)[0]
        self.assertEqual(sheet.opening(t), "անշարժ")
        self.assertIn("Բացում՝ անշարժ", sheet.info_lines(t))


if __name__ == "__main__":
    unittest.main()
