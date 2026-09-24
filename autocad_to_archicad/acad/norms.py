"""The Armenian norms and laws a site model like this touches, what the tool checks against each, and the
calculations the report makes from them (parking demand, building density).

Numbers are those of ՀՀՇՆ 30-01-2023 (read from its text, arlis.am, order N 04-Ն of 22 May 2023, in force since
30 May 2023). Where the tool only points to a norm, the designers check it; the report says so.
"""
import fnmatch

REGISTER = [
    ("«Քաղաքաշինության մասին» օրենք (Law on Urban Development); Government decision N 596-Ն of 19 March 2015",
     "planning assignment, construction permit, completion and occupancy procedure",
     "not checked - the permit path of the project"),
    ("ՀՀՇՆ 30-01-2023 Urban planning: planning and development of urban and rural settlements",
     "street classes, widths and design speeds (Tables 28-29); junctions (kerb radius 12 m, 6 m constrained; sight "
     "triangles 25 / 40 / 65 m at 40 / 60 / 80 km/h); dead ends (turning place 15 m); wheelchair paths (at most 1:12, "
     "landings); parking (Table 56); density and coverage (Table 8); gaps between buildings (10 m; fire Table 50); "
     "fire access (street within 25 m, 5-8 / 8-10 m from the wall); least earthworks, keep the natural relief",
     "checked: street classes and profiles, kerb radii, dead ends, sidewalk widths, wheelchair grades, parking "
     "demand, density, gaps and fire access of the new buildings"),
    ("ՀՀՇՆ 32-01-2022 Automobile roads",
     "geometry by design speed: radius, grade, vertical curves, sight distance, widening in bends, serpentines",
     "used for the profiles (values of the SNiP 2.05.02-85 table it continues - to be confirmed against its text)"),
    ("ՀՀՇՆ 30-02-2022 Territory improvement (landscaping)", "sight triangles, fire lanes, paving, planting",
     "not checked"),
    ("ՀՀՇՆ 20.04-2020 Earthquake-resistant construction", "Yerevan is in a high seismic zone: structure, heights, gaps",
     "not checked - structural design"),
    ("ՀՀՇՆ 21-01-2014 Fire safety of buildings and structures", "fire resistance degrees behind the Table 50 distances",
     "the 6 m distance (I-II degree) is checked"),
    ("ՀՀՇՆ IV-11.07.01-2006 Accessibility of buildings for people with limited mobility", "ramps, entrances, routes",
     "sidewalk grades are checked against 1:12"),
    ("ՀՀՇՆ IV-11.03.03-2002 (ՄՍՆ 2.02.05-2000) Car parks", "underground parking design (ramps, heights, fire)",
     "not checked - the level outlines and areas of the documents are modelled"),
    ("ՀՀՇՆ 31-01-2014 Residential buildings; ՀՀՇՆ 31-03-2020 Public buildings", "the buildings themselves",
     "not checked"),
    ("ՀՀՇՆ 22-03-2017 Artificial and natural lighting", "insolation / daylight between buildings",
     "not checked - the 3D model can be used for a sun study"),
    ("ՀՀՇՆ 22-04-2014 Noise protection", "50 m from main roads to housing (25 m with noise measures)", "not checked"),
    ("ՀՀՇՆ 22-02.01-2023 Protection from dangerous geological processes", "landslides, slopes, retaining structures",
     "the retaining walls and bridges the streets need are found and modelled; their design is not"),
    ("ՀՀՇՆ 31-03.02-2022 Civil defence shelters", "underground parking up to 80 % coverage when it can serve as a shelter "
     "(Table 8, note 12)", "not checked"),
    ("Law on the protection and use of immovable monuments of history and culture and of the historical environment",
     "protection and development-control zones of monuments near the site, views of them "
     "(ՀՀՇՆ 30-01-2023 chapter on monuments; Table 49 distances to infrastructure)",
     "not checked - ask the municipality / the Ministry of Education, Science, Culture and Sport for the zones"),
]


def parking_demand(functions, rules):
    """Parking spaces the programme needs (ՀՀՇՆ 30-01-2023 Table 56): [(function, m2, rule text, low, high)]."""
    rows = []
    for name, m2 in functions.items():
        rule = next((r for pat, r in rules.items() if not pat.startswith("_") and fnmatch.fnmatchcase(name.upper(), pat)), None)
        if rule is None:
            rows.append((name, m2, "no rule", None, None))
        elif "m2_per_space" in rule:
            a, b = rule["m2_per_space"]
            rows.append((name, m2, f"1 space per {a}-{b} m² ({rule.get('source', '')})", m2 / b, m2 / a))
        elif "unit_m2" in rule:
            units = m2 / float(rule["unit_m2"])
            a, b = rule["spaces_per_unit"]
            rows.append((name, m2, f"{a:g}-{b:g} spaces per unit of {rule['unit_m2']} m² ({rule.get('source', '')})",
                         units * a, units * b))
        else:
            rows.append((name, m2, rule.get("note", "not counted"), None, None))
    return rows
