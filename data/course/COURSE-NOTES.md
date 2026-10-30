# Route du Rhum – Destination Guadeloupe 2026: course definition

Compiled on 25/10/2026 for the weather router. Every value has a source. Confidence levels:
- **CONFIRMED**: read in an official 2026 document.
- **CROSS-CHECKED**: CONFIRMED, and it also matches the organiser's Adrena files.
- **DERIVED**: computed or inferred from confirmed values. The reasoning is given.
- **UNCONFIRMED**: not found in any source.

Machine-readable version: `course-2026.geojson`, in this folder. It has 37 features: zones, marks, lines and the rounding rule. Coordinates are in WGS84, in lon,lat order.

## 0. Sources (all downloaded into `sources/`)

| Short name | Document | Origin |
|---|---|---|
| **SI-FR** | Instructions de Course 2026, including amendment 1 (09/10/2026) and amendment 2 (18/10/2026). French prevails. | Drive "02. Instructions de courses", file id `1LGlrw0n1OLk7QExBku09wRsaRn-q38tN` → `sources/IC-RDRDG-2026-integrant-avenant-1-2_FR.pdf` |
| SI-EN | Sailing Instructions 2026 FINAL, **before** amendments 1 and 2 | file id `1MNX8HBx3d6JWZJHMOEeV4uuFM-Z7_QX8` → `sources/SI-RDRDG-2026-FINAL_EN.pdf` |
| SI-AV3, SI-AV4 | SI amendments 3 (22/10) and 4 (24/10). They only change the navigation-light check date. No course change. | `sources/IC-RDRDG-2026-AVENANT-3.pdf`, `-4.pdf` |
| **NoR** | Notice of Race 2026 (EN), including AV2 | https://547c0f02-b1a4-4e3a-adf9-2dd91d16579d.usrfiles.com/ugd/547c0f_a1eb78cd3c3b457f86c61476a3e415b3.pdf → `sources/RDR2026-NoR-AV2-FR-EN.pdf` |
| NoR-AV4, AV5 | NoR amendments 4 (17/10) and 5 (22/10). Programme changes only. | `sources/AC-RDRDG-2026-AVENANT-4.pdf`, `-5.pdf` |
| **Adrena** | Organiser's zone files (.cl10, plain text): 21 forbidden zones and 2 vigilance zones | Drive "09. Fichiers Adrena" → `sources/adrena-cl10/` |
| PreMar | Atlantic maritime prefecture decree n° 2026/160, Saint-Malo start | `sources/StMalo-Arrete-PreMar-depart.pdf` |
| VR-cal | Virtual Regatta calendar, with the JSON embedded in the page | https://www.virtualregatta.com/en/calendar/ |
| VR-art | VR article, 01/10/2026 | https://www.virtualregatta.com/en/route-du-rhum-destination-guadeloupe-2026-virtual-regatta/ |
| VR-cat | VR article, 10/10/2026 (classes and durations) | https://www.virtualregatta.com/en/route-du-rhum-2026-quelle-categorie-choisir/ |

Index of official documents: Espace Skippers https://www.routedurhum.com/espace-skippers → "DRIVE SKIPPER" https://drive.google.com/drive/folders/1rgPD37HngXLRX29g5_ZVwMIXQo2ZDJLK. That public folder holds the NoR, SI, Adrena files, briefings and decrees.

Not used:
- `Briefing-Point-arrivee-Ultims-13-10.pdf`: covers the boats' arrival in Saint-Malo before the race, not the course.
- `Guadeloupe-Arrete-interprefectoral-arrivees.pdf`: a scan with no text layer, not read.

## 1. Start

| Item | Value | Confidence / source |
|---|---|---|
| Start signal | **Sunday 01/11/2026 12:02:00 UTC** (13:02 French time, 08:02 Guadeloupe time) | CONFIRMED, SI-FR 9.2 and NoR 8.1 |
| Signals | Warning 11:54, preparatory 11:58 (flag I), one-minute 12:01, start 12:02 UTC (RRS 26) | CONFIRMED, SI-FR 9.2 |
| Weather changes | Race Management may bring the start forward 1 day (amendment ≥ 48 h ahead) or postpone it (amendment ≥ 24 h ahead) | CONFIRMED, NoR 8.1 |
| Line | Runs N–S along **001°54.000'W** and is crossed **westward**. Committee boat at 48°45.000'N, mid-line. "Approximate coordinates" (SI 9.3). | CONFIRMED, SI-FR 9.3 |
| **Ultim / Ocean Fifty segment** | From the north intermediate orange buoy **48°45.500'N 001°54.000'W** (48.758333, -1.900000) to the north sighting boat **48°46.500'N 001°54.000'W** (48.775000, -1.900000). Centre: **48°46.000'N 001°54.000'W** (48.766667, -1.900000). | CONFIRMED for the coordinates. The segment assignment is DERIVED: Ultim and Ocean Fifty leave the orange buoy to port while heading west, so they start north of it. |
| Other segments (same longitude) | Vintage Multi/Mono 48°45.000'–48°45.500'N. IMOCA 48°44.100'–48°45.000'N. Class40 48°43.500'–48°44.100'N. | CONFIRMED / DERIVED, as above |
| Wrong segment / OCS | A boat that crosses a segment not assigned to it, or starts early (DR21-01), gets a **5 h** penalty. It is served after the Fréhel gate and within 24 h. | CONFIRMED, SI-FR 9.5–9.7 |
| Late start | Allowed up to 72 h. Racing time is still counted from 12:02 UTC. A late starter is racing from the longitude of the Saint-Malo landfall buoy, **002°07.300'W**. | CONFIRMED, SI-FR 8.2 |
| Course area polygon | RDR1 48°51.000'N 002°23.500'W, RDR2 48°51.000'N 001°50.100'W, RDR3 48°43.445'N 001°50.100'W (Bell Ruet), RDR4 48°42.700'N 001°50.700'W (Pointe du Grouin), RDR5 48°40.100'N 001°59.200'W, RDR6 48°40.100'N 002°23.500'W | CONFIRMED, SI-FR Annexe 3A and PreMar annexe I. Final perimeter published ≤ 48 h before the start. |

**Virtual Regatta (VR Offshore)**: there are 5 separate races, one per class. **All 5 start at 2026-11-01T12:02:00.000Z**, the same minute as the real race. Close: 2026-11-30T13:00Z. Race type is `synchronous`. CONFIRMED by VR-cal (embedded JSON) and VR-art ("Cinq classes, cinq courses, cinq classements").
- Ultim **raceId 797**, leg 1
- Class40 844
- IMOCA 845
- Ocean Fifty 846
- Vintage Multi 847
- Vintage Mono is not playable.

So there is **no staggered start in 2026**. In 2022, VR had separate starts per class: 13:15/13:25/13:35/13:45 UTC (zezo forum tid=8598). That does not carry over to 2026. Whether VR follows a real-race postponement is UNCONFIRMED (SUPPOSED yes: "synchronous", and it did so in 2022). The in-game start line geometry is UNCONFIRMED.

## 2. Course, marks and sides (SI-FR Annexe 3, current text)

Order of passage:

| # | Mark | Rule | Position | Confidence |
|---|---|---|---|---|
| 0 | Start line | §1 | – | CONFIRMED |
| 1 | **Porte Fréhel** (gate) | Pass **between** the two inflatable yellow cylinders, westbound | Fréhel Nord **48°42.800'N 002°18.500'W** (48.713333, -2.308333). Fréhel Sud **48°41.800'N 002°18.500'W** (48.696667, -2.308333). Fréhel Nord may be moved on start day; its longitude stays the same. | CONFIRMED. Gate width ≈ 1.0 nm. |
| 2 | **Ile de la Guadeloupe** | **Round leaving it to port**, i.e. anticlockwise: north of Grande-Terre, west coast southbound, then east past the south of Basse-Terre | – | Rule CONFIRMED. Direction DERIVED. |
| 3 | **Ilot La Tête à l'Anglais** (NW of Basse-Terre) | **Leave to port** | No coordinates in the SI. ≈ **16°22.850'N 061°45.850'W** (16.380833, -61.764167): vertex A of the SI's ZPC AGOA zone. It matches BirdLife's 16°22'54"N 61°45'52"W (https://datazone.birdlife.org/site/factsheet/islet-of-tête-à-l’anglais-iba-guadeloupe-(to-france)/map). | Side CONFIRMED. Position DERIVED, 2 sources agree. |
| 4 | **Bouée « Basse-Terre »** (off Basse-Terre town, leeward coast) | **Leave to starboard.** Amendment 2 replaced "contourner en la laissant à tribord" with "laisser à tribord". | **15°59.250'N 061°44.190'W** (15.987500, -61.736500). White flash light at night if possible. Restricted zone of **0.25 nm radius** around it (Annexe 3B). | CONFIRMED. Southbound with the mark to starboard, the boat passes **inshore** (east) of the buoy, between it and the Stade nautique Basse-Terre zone (gap ≈ 0.5 nm). That reading is DERIVED. The 3B restricted zone is SUPPOSED to target spectator craft, not competitors. |
| 5 | **Archipel des Saintes** | **Leave to starboard.** Eastbound, this means passing **north** of Les Saintes, through the Canal des Saintes. | No coordinates in the SI. Centre 15°51'40"N 61°36'35"W (fr.wikipedia infobox, https://fr.wikipedia.org/wiki/Îles_des_Saintes). Use a coastline polygon. | Side CONFIRMED. Passage north DERIVED. |
| 6 | **Bouée d'atterrissage PP** | **Round to port.** Amendment 1 changed "laisser" to "contourner". | **16°09.570'N 061°31.330'W** (16.159500, -61.522167). Amendment 2 corrected the position. It is point D of the approach corridor. | CONFIRMED |
| 7 | **Finish line** | Cross northward, inside the approach corridor | See §4 | CONFIRMED |

- **Pointe du Vieux-Fort** is **not a mark** in 2026. It does not appear in the SI or NoR course. It is only coastline to clear.
- NoR art. 11 (summary): start north of Pointe du Grouin, Cap Fréhel gate, round Guadeloupe to port, Tête à l'Anglais to port, Basse-Terre mark to starboard, finish near Pointe-à-Pitre.
- SI Annexe 3: if a mark is missing, its published position counts as a waypoint.
- The ZPC AGOA forbidden zone (§3) runs from Tête à l'Anglais to off Pointe de la Grande Vigie (16°30.65'N 61°28.45'W). The approach along the north of Guadeloupe must therefore stay **north of the line Grande Vigie → Tête à l'Anglais**. DERIVED from the polygon.

## 3. Forbidden zones (SI-FR 8.3 and Annexe 4)

SI 8.3 says:
- Boats shall neither enter nor sail in these zones, nor in those defined in nautical documents.
- They count as **obstacles**.
- A cetacean protection zone may only be crossed for a technical stop, with Race Direction's agreement.
- More zones may be published by amendment (8.4).

All vertices below are **CROSS-CHECKED**: the SI text and the Adrena files differ by at most 0.000 nm, except Finisterre (≤ 0.21 nm) and the Canaries (≤ 0.02 nm). The GeoJSON uses the SI values.

Vertices are given as lat N, lon W, in degrees and decimal minutes, in SI order. Close each polygon from the last vertex back to the first.

**Brittany / start**
- **ZI Plaisanciers**: 48°41.000 002°23.500; 48°41.700 002°20.000; 48°40.835 002°19.610; 48°41.090 002°18.890; 48°42.850 001°58.220; 48°43.900 001°50.100. It is a boundary line closed by the coast: the zone lies between this line and the coast, south of the start corridor. **Do not close it straight from the last vertex to the first**: that segment would cut the race corridor. The GeoJSON adds the coast-following Adrena polygon (2 parts).
- **Parc éolien Saint-Brieuc**: 48°55.800 002°34.150; 48°53.100 002°30.000; 48°49.050 002°27.250; 48°47.800 002°26.900; 48°47.500 002°30.550; 48°48.350 002°33.300; 48°49.200 002°34.550; 48°53.800 002°37.100; 48°54.550 002°37.000
- **Moulières Binic**: 48°36.070 002°46.640; 48°36.320 002°46.150; 48°35.610 002°45.380; 48°35.380 002°45.860

**Traffic separation schemes and the English Channel / Celtic Sea**
- **TSS Ouessant (long)**: 49°04.550 005°30.100; 48°51.090 005°18.380; 48°41.040 005°06.960; 48°25.520 005°26.830; 48°30.650 005°46.360; 48°38.160 006°06.860; 48°56.400 005°51.600
- **TSS West Scilly**: 50°01.070 006°32.750; 49°52.300 006°36.600; 49°52.400 006°53.700; 50°03.950 006°48.450
- **TSS South Scilly**: 49°46.050 006°16.550; 49°35.540 006°16.400; 49°35.550 006°34.100; 49°46.030 006°29.550
- **TSS Seven Stones**: 50°20.000 006°05.000; 50°20.000 005°49.500; 50°00.970 005°49.600; 49°53.550 006°04.980
- **TSS Fastnet**: 51°21.300 009°36.700; 51°22.900 009°27.400; 51°17.150 009°24.600; 51°15.400 009°33.900

**Bay of Biscay (wind farms)**
- **Banc de Guérande**: 47°08.750 002°42.250; 47°10.750 002°41.500; 47°12.250 002°41.750; 47°12.750 002°39.500; 47°10.000 002°30.750; 47°09.000 002°29.750; 47°07.000 002°33.000
- **Yeu**: 46°56.600 002°31.672; 46°50.977 002°24.995; 46°48.521 002°29.385; 46°53.190 002°34.907; 46°54.793 002°34.954
- **Turbines SEM-REV**: 47°14.800 002°46.550; 47°14.350 002°46.000; 47°13.900 002°46.900; 47°14.350 002°47.500

**Iberia**
- **TSS Cap Finisterre (long)**: 43°35.900 010°02.000; 43°25.500 009°33.380; 43°10.500 009°44.000; 42°47.750 009°44.000; 42°47.750 010°13.850; 43°18.950 010°13.850
- **Parc éolien Viana do Castelo**: 41°41.830 009°05.280; 41°41.830 009°02.000; 41°40.520 009°02.000; 41°40.520 009°05.280
- **TSS Cape Roca**: 38°52.000 009°41.100; 38°39.700 009°40.000; 38°33.900 010°11.700; 38°40.900 010°13.800; 38°52.000 010°13.800
- **TSS Cabo São Vicente**: 37°02.500 009°11.700; 36°56.700 009°10.300; 36°51.500 009°04.300; 36°50.100 008°57.200; 36°25.200 009°06.000; 36°28.460 009°21.600; 36°44.200 009°39.850; 36°56.600 009°43.300

**Atlantic**
- **ZPC Açores (cetaceans)**: 39°50 032°00; 40°44 030°24; 40°10 026°52; 38°30 024°34; 37°15 023°40; 36°20 024°32; 36°20 026°47; 37°11 028°20; 37°17 031°15; 37°47 032°00. This large zone blocks a direct Azores route.
- **TSS Canaries Est**: 28°19.800 014°47.700; 27°48.780 015°00.350; 27°51.500 015°08.850; 28°20.500 014°57.100
- **TSS Canaries Ouest**: 28°33.800 015°39.300; 27°58.400 016°12.950; 28°03.450 016°19.650; 28°38.100 015°46.800
- **ZI Mauritanie**: 21°31 016°25; 16°00 016°25; 16°00 017°35; 21°31 017°35

**Guadeloupe**
- **ZPC AGOA Guadeloupe (cetaceans)**: 16°22.850 061°45.850; 16°30.650 061°28.450; 16°26.250 061°32.450; 16°20.500 061°30.500; 16°20.000 061°41.650
- **Stade nautique Basse-Terre**: 15°59.700 061°43.910; 15°59.135 061°43.380; 15°59.070 061°43.435; 15°59.645 061°43.995
- **Stade nautique Pointe-à-Pitre**: 16°12.680 061°31.720; 16°12.750 061°31.360; 16°12.453 061°30.505; 16°12.320 061°30.300; 16°12.000 061°30.300; 16°12.000 061°30.570; 16°12.280 061°30.570; 16°12.560 061°31.000; 16°12.600 061°31.685

**Vigilance zones (allowed, but keep a cetacean watch; not obstacles)**
- **AGOA Guadeloupe**, west of Basse-Terre: 16°14.400 061°55.200; 16°17.500 061°52.400; 16°17.500 061°50.400; 16°12.900 061°50.400; 16°10.100 061°54.150; 16°11.300 061°55.750
- **Madère**: 33°30 017°00; 33°30 015°45; 32°30 015°45; 32°00 016°30; 32°30 017°45

No ice limit exists for this race. Neither the SI nor the NoR defines one.

**VR game zones**: the VR exclusion zones and in-game gates for races 797, 844–847 are **UNCONFIRMED**. They are only visible in the game client. No public page lists them. zezo.org had not set up the race as of 19/10 (forum tid=9145), and toxcct.free.fr no longer resolves (DNS). VR says it uses "the same course" (VR-art) but gives no zone list. To check: open race 797 in VR Offshore after the race opens (race info / map) and compare with this list.

The **prologue** (September) had a logo-shaped zone in the Bay of Biscay with a 70 % slowdown (https://jv.jeuxonline.info/actualite/66453/virtual-regatta-detaille-route-rhum-virtuelle-2026). That zone belongs to the prologue, not to the main race.

## 4. Finish (SI-FR 10.1 and Annexe 3C)

- **Line**: along latitude **16°12.000'N**, crossed northward.
  - West end: orange cylindrical buoy **16°12.000'N 061°31.050'W** (16.200000, -61.517500). Flashing orange at night.
  - East end: committee catamaran with a blue flag, **16°12.000'N 061°30.800'W** (16.200000, -61.513333). White LED band at night.
  - Length ≈ 0.24 nm. CONFIRMED.
- **Approach corridor** (restricted zone, orange): A 16°12.000'N 061°31.100'W; B 16°12.000'N 061°30.570'W (yellow rigid buoy); C 16°09.570'N 061°30.520'W; D 16°09.570'N 061°31.330'W (PP buoy). CONFIRMED.
- **Pick-up zone** after the line (pink): E 16°12.600 061°31.685; F 16°12.560 061°31.000; G 16°12.280 061°30.570; B; A. CONFIRMED.
- **Line closes**: 03/12/2026 12:02 UTC (SI 11.1; NoR 12 gives start + 32 days). VR closes 30/11/2026 13:00 UTC (VR-cal).
- VR finish line: "même ligne d'arrivée" (VR-art). Its exact in-game coordinates are UNCONFIRMED.

## 5. Durations (forecast horizon)

| Class | Reference | Source |
|---|---|---|
| **Ultim record** | **6 d 19 h 47 min 25 s**, Charles Caudrelier, Maxi Edmond de Rothschild, 2022. 2nd: Gabart 6 d 23 h 03 min. 3rd: Coville 7 d 06 h 37 min. | https://en.wikipedia.org/wiki/2022_Route_du_Rhum. Also VR-cat. |
| Ultim (VR) | "7 to 8 days" | VR-cal |
| Ocean Fifty / IMOCA / Class40 | 2022 winners: 10 d 21 h / 11 d 17 h / 14 d 3 h. VR estimates 11–13 / 12–14 / 15–18 days. | VR-cat, VR-cal |
| Distance | 3,542 nm | VR-art |

Sizing: for an Ultim, an **8–10 day** horizon covers the whole race. For a start on 01/11 12:02Z, expect an ETA of about 08–09/11. VR updates its weather every 6 h (https://www.routedurhum.com/en/post/virtual-regatta-game-open).

## 6. What is still unconfirmed or open

1. Final start line and course area: positions are "approximate" and get confirmed ≤ 48 h before the start. Watch for amendments on the skipper Drive, especially if the start moves.
2. In-game VR elements: gates, exclusion zones, exact finish line, and any limit of its own.
3. Coastline polygons for Les Saintes and the north of Grande-Terre: use a coastline dataset.
4. Possible new cetacean zones by amendment (SI 8.4 and NoR 11).
5. Scanned Guadeloupe prefecture decree (arrivals): not read. It may restrict the approach to Pointe-à-Pitre for spectators.
