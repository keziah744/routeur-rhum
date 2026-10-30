# Builds course-2026.geojson from the SI 2026 (FR, integrating amendments 1 & 2) coordinates,
# and cross-checks every SI vertex against the organiser's Adrena .cl10 files.
import json, os, math, sys
sys.stdout.reconfigure(encoding="utf-8")
SRC_DIR, OUT = sys.argv[1], sys.argv[2]


def dm(d, m, hemi):  # degrees + decimal minutes -> decimal degrees
    v = d + m / 60.0
    return round(-v if hemi in "WS" else v, 6)


def P(lat, lon):  # "48 41.000", "2 23.500" ; N and W implied (whole course is N/W)
    a, b = lat.split()
    c, d = lon.split()
    return [dm(int(c), float(d), "W"), dm(int(a), float(b), "N")]  # GeoJSON order lon,lat


SI = "SI 2026 FR integrant avenants 1 & 2 (Annexe 4)"
zones = {
    "ZI Plaisanciers (SI P1-P6, ferme par la cote)": ("forbidden_polyline_coast", None, [("48 41.000", "2 23.500"), ("48 41.700", "2 20.000"), ("48 40.835", "2 19.610"), ("48 41.090", "2 18.890"), ("48 42.850", "1 58.220"), ("48 43.900", "1 50.100")]),
    "ZI Parc eolien Saint-Brieuc": ("forbidden", "ZI_Parc_eolien_Saint-Brieuc.cl10", [("48 55.800", "2 34.150"), ("48 53.100", "2 30.000"), ("48 49.050", "2 27.250"), ("48 47.800", "2 26.900"), ("48 47.500", "2 30.550"), ("48 48.350", "2 33.300"), ("48 49.200", "2 34.550"), ("48 53.800", "2 37.100"), ("48 54.550", "2 37.000")]),
    "ZI Moulieres Binic": ("forbidden", "ZI_Moulieres_Binic.cl10", [("48 36.070", "2 46.640"), ("48 36.320", "2 46.150"), ("48 35.610", "2 45.380"), ("48 35.380", "2 45.860")]),
    "ZI TSS Ouessant (long)": ("forbidden", "TSS_Ouessant.cl10", [("49 04.550", "5 30.100"), ("48 51.090", "5 18.380"), ("48 41.040", "5 06.960"), ("48 25.520", "5 26.830"), ("48 30.650", "5 46.360"), ("48 38.160", "6 06.860"), ("48 56.400", "5 51.600")]),
    "ZI Parc eolien Banc de Guerande": ("forbidden", "ZI_Parc_eolien_Banc_Guerande.cl10", [("47 08.750", "2 42.250"), ("47 10.750", "2 41.500"), ("47 12.250", "2 41.750"), ("47 12.750", "2 39.500"), ("47 10.000", "2 30.750"), ("47 09.000", "2 29.750"), ("47 07.000", "2 33.000")]),
    "ZI Parc eolien Yeu": ("forbidden", "ZI_Parc_eolien_Yeu.cl10", [("46 56.600", "2 31.672"), ("46 50.977", "2 24.995"), ("46 48.521", "2 29.385"), ("46 53.190", "2 34.907"), ("46 54.793", "2 34.954")]),
    "ZI Turbines maremotrices SEM-REV": ("forbidden", "ZI_Turbines_maremotrices.cl10", [("47 14.800", "2 46.550"), ("47 14.350", "2 46.000"), ("47 13.900", "2 46.900"), ("47 14.350", "2 47.500")]),
    "ZI TSS West Scilly": ("forbidden", "TSS_West_Scilly.cl10", [("50 01.070", "6 32.750"), ("49 52.300", "6 36.600"), ("49 52.400", "6 53.700"), ("50 03.950", "6 48.450")]),
    "ZI TSS South Scilly": ("forbidden", "TSS_South_Scilly.cl10", [("49 46.050", "6 16.550"), ("49 35.540", "6 16.400"), ("49 35.550", "6 34.100"), ("49 46.030", "6 29.550")]),
    "ZI TSS Seven Stones": ("forbidden", "ZI_TSS_Seven_Stones.cl10", [("50 20.000", "6 05.000"), ("50 20.000", "5 49.500"), ("50 00.970", "5 49.600"), ("49 53.550", "6 04.980")]),
    "ZI TSS Fastnet": ("forbidden", "ZI_TSS_Fastnet.cl10", [("51 21.300", "9 36.700"), ("51 22.900", "9 27.400"), ("51 17.150", "9 24.600"), ("51 15.400", "9 33.900")]),
    "ZI TSS Cap Finisterre (long)": ("forbidden", "TSS_Finisterre_long.cl10", [("43 35.900", "10 02.000"), ("43 25.500", "9 33.380"), ("43 10.500", "9 44.000"), ("42 47.750", "9 44.000"), ("42 47.750", "10 13.850"), ("43 18.950", "10 13.850")]),
    "ZI Parc eolien Viana do Castelo": ("forbidden", "ZI_Parc_eolien_Viana.cl10", [("41 41.830", "9 05.280"), ("41 41.830", "9 02.000"), ("41 40.520", "9 02.000"), ("41 40.520", "9 05.280")]),
    "ZI TSS Cape Roca": ("forbidden", "TSS_Cape_Roca.cl10", [("38 52.000", "9 41.100"), ("38 39.700", "9 40.000"), ("38 33.900", "10 11.700"), ("38 40.900", "10 13.800"), ("38 52.000", "10 13.800")]),
    "ZI TSS Cabo Sao Vicente": ("forbidden", "TSS_Cabo_Sao_Vicente.cl10", [("37 02.500", "9 11.700"), ("36 56.700", "9 10.300"), ("36 51.500", "9 04.300"), ("36 50.100", "8 57.200"), ("36 25.200", "9 06.000"), ("36 28.460", "9 21.600"), ("36 44.200", "9 39.850"), ("36 56.600", "9 43.300")]),
    "ZI TSS Canaries Est": ("forbidden", "TSS_Canaries_Est.cl10", [("28 19.800", "14 47.700"), ("27 48.780", "15 00.350"), ("27 51.500", "15 08.850"), ("28 20.500", "14 57.100")]),
    "ZI TSS Canaries Ouest": ("forbidden", "TSS_Canaries_Ouest.cl10", [("28 33.800", "15 39.300"), ("27 58.400", "16 12.950"), ("28 03.450", "16 19.650"), ("28 38.100", "15 46.800")]),
    "ZI Mauritanie": ("forbidden", "ZI_Mauritanie.cl10", [("21 31.000", "16 25.000"), ("16 00.000", "16 25.000"), ("16 00.000", "17 35.000"), ("21 31.000", "17 35.000")]),
    "ZI ZPC Acores (cetaces)": ("forbidden", "ZI_ZPC_Acores.cl10", [("39 50.000", "32 00.000"), ("40 44.000", "30 24.000"), ("40 10.000", "26 52.000"), ("38 30.000", "24 34.000"), ("37 15.000", "23 40.000"), ("36 20.000", "24 32.000"), ("36 20.000", "26 47.000"), ("37 11.000", "28 20.000"), ("37 17.000", "31 15.000"), ("37 47.000", "32 00.000")]),
    "ZI ZPC AGOA Guadeloupe (cetaces)": ("forbidden", "ZI_ZPC_AGOA_Guadeloupe.cl10", [("16 22.850", "61 45.850"), ("16 30.650", "61 28.450"), ("16 26.250", "61 32.450"), ("16 20.500", "61 30.500"), ("16 20.000", "61 41.650")]),
    "ZI Stade nautique Basse-Terre": ("forbidden", "ZI_Guadeloupe_Stades_Nautiques.cl10", [("15 59.700", "61 43.910"), ("15 59.135", "61 43.380"), ("15 59.070", "61 43.435"), ("15 59.645", "61 43.995")]),
    "ZI Stade nautique Pointe-a-Pitre": ("forbidden", "ZI_Guadeloupe_Stades_Nautiques.cl10", [("16 12.680", "61 31.720"), ("16 12.750", "61 31.360"), ("16 12.453", "61 30.505"), ("16 12.320", "61 30.300"), ("16 12.000", "61 30.300"), ("16 12.000", "61 30.570"), ("16 12.280", "61 30.570"), ("16 12.560", "61 31.000"), ("16 12.600", "61 31.685")]),
    "Zone de vigilance AGOA Guadeloupe": ("vigilance", "Vigilance_AGOA_Guadeloupe.cl10", [("16 14.400", "61 55.200"), ("16 17.500", "61 52.400"), ("16 17.500", "61 50.400"), ("16 12.900", "61 50.400"), ("16 10.100", "61 54.150"), ("16 11.300", "61 55.750")]),
    "Zone de vigilance Madere": ("vigilance", "Vigilance_Madere.cl10", [("33 30.000", "17 00.000"), ("33 30.000", "15 45.000"), ("32 30.000", "15 45.000"), ("32 00.000", "16 30.000"), ("32 30.000", "17 45.000")]),
}


def read_cl10(fn):
    out = []
    raw = open(os.path.join(SRC_DIR, fn), "rb").read().decode("latin1")
    for line in raw.splitlines():
        if not line.startswith("S;"):
            continue
        F = line.split(";")
        n = int(F[20])
        pts = [(float(F[22 + 2 * i]), float(F[21 + 2 * i])) for i in range(n)]  # (lon, lat)
        out.append(pts[1:])  # first pair is the label anchor, not a vertex
    return out


def nm(a, b):
    dlat = (a[1] - b[1]) * 60
    dlon = (a[0] - b[0]) * 60 * math.cos(math.radians(a[1]))
    return math.hypot(dlat, dlon)


feats = []
for name, (kind, cl, verts) in zones.items():
    coords = [P(*v) for v in verts]
    if cl:
        allp = [p for r in read_cl10(cl) for p in r]
        dev = max(min(nm(c, p) for p in allp) for c in coords)
        print(f"{name:45s} SI vs {cl}: max vertex deviation {dev:.3f} nm")
    if kind == "forbidden_polyline_coast":
        geom = {"type": "LineString", "coordinates": coords}
        kind = "forbidden_boundary"
    else:
        geom = {"type": "Polygon", "coordinates": [coords + [coords[0]]]}
    feats.append({"type": "Feature", "properties": {"name": name, "kind": kind, "source": SI, "cl10": cl}, "geometry": geom})

for i, r in enumerate(read_cl10("ZI_Zone_plaisanciers.cl10")):
    feats.append({"type": "Feature", "properties": {"name": f"ZI Plaisanciers (Adrena detail, part {i + 1})", "kind": "forbidden", "source": "Adrena file ZI Zone plaisanciers.cl10 (organiser Drive, 09. Fichiers Adrena)"}, "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in r] + [list(r[0])]]}})


def pt(name, lat, lon, **pr):
    feats.append({"type": "Feature", "properties": {"name": name, **pr}, "geometry": {"type": "Point", "coordinates": P(lat, lon)}})


def ln(name, a, b, **pr):
    feats.append({"type": "Feature", "properties": {"name": name, **pr}, "geometry": {"type": "LineString", "coordinates": [P(*a), P(*b)]}})


S9 = "SI 2026 9.3 (approximate, final positions published up to 48 h before start)"
ln("Start line Ultim / Ocean Fifty", ("48 45.500", "1 54.000"), ("48 46.500", "1 54.000"), kind="start_line", order=0, cross="westward", source=S9)
ln("Start line Vintage Multi / Vintage Mono", ("48 45.000", "1 54.000"), ("48 45.500", "1 54.000"), kind="start_line", order=0, cross="westward", source=S9)
ln("Start line IMOCA", ("48 44.100", "1 54.000"), ("48 45.000", "1 54.000"), kind="start_line", order=0, cross="westward", source=S9)
ln("Start line Class40", ("48 43.500", "1 54.000"), ("48 44.100", "1 54.000"), kind="start_line", order=0, cross="westward", source=S9)
ln("Porte Frehel (gate)", ("48 41.800", "2 18.500"), ("48 42.800", "2 18.500"), kind="gate", order=1, cross="westward, between the two yellow buoys", note="Frehel Nord may be moved on start day, same longitude", source="SI 2026 Annexe 3")
feats.append({"type": "Feature", "properties": {"name": "Ile de la Guadeloupe", "kind": "rounding_rule", "order": 2, "side": "port", "note": "Round the island leaving it to port (anticlockwise): north of Grande-Terre, then west coast southbound, then east past the south of Basse-Terre", "source": "SI 2026 Annexe 3"}, "geometry": None})
pt("Ilot La Tete a l'Anglais", "16 22.850", "61 45.850", kind="mark", order=3, side="port", note="Natural islet, no coordinates in SI. Position = vertex A of ZI ZPC AGOA (SI Annexe 4), matches BirdLife 16 22 54 N / 61 45 52 W", source="SI Annexe 3 (side); SI Annexe 4 + BirdLife (position)")
pt("Bouee Basse-Terre", "15 59.250", "61 44.190", kind="mark", order=4, side="starboard", restricted_radius_nm=0.25, source="SI 2026 Annexe 3 and 3B (amendment 2)")
pt("Archipel des Saintes (centre)", "15 51.667", "61 36.583", kind="mark", order=5, side="starboard", note="Natural archipelago; centre from fr.wikipedia infobox (15 51 40 N / 61 36 35 W); enforce with a coastline polygon", source="SI Annexe 3 (side); Wikipedia (position)")
pt("Bouee d'atterrissage PP", "16 09.570", "61 31.330", kind="mark", order=6, side="port", rounding=True, source="SI 2026 Annexe 3 (amendments 1 and 2)")
ln("Finish line", ("16 12.000", "61 31.050"), ("16 12.000", "61 30.800"), kind="finish_line", order=7, cross="northward", note="W end orange cylindrical buoy, E end committee catamaran (blue flag)", source="SI 2026 10.1")

json.dump({"type": "FeatureCollection", "name": "Route du Rhum - Destination Guadeloupe 2026, real-race course", "features": feats}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", OUT, len(feats), "features")
