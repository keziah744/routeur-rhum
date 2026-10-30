# Polar sources: Virtual Regatta Offshore Ultim

All files retrieved 2026-10-25. Every file is untrusted third-party data, stored as downloaded and never edited. The `code/` files are saved as `.txt` so they cannot be run by accident.

## Best file for the Route du Rhum 2026 router

`civis_api_polars_Ultim_BP_XI.json`: VR polar `_id` 21, label "Ultim BP XI", VR `_updatedAt` 2024-07-02T18:33:41.810Z. It is plain JSON in VR's own `Meta_GetPolar` format.

`ityc_export_Ultim_BP_XI.json` is a second, independent copy. Its numbers are identical, but it is wrapped in JS (`data_Ultim_BP_XI = '[...]'`).

The link between the race and this polar comes from `civis_api_races.json`. That file lists race `797.1`, "Route du Rhum - Ultim", with boat `Ultim BP XI`, starting 2026-11-01T12:02Z. The mapping is third party, not from VR.

## Files

| File | URL | Contents | Polar version | Confidence |
|---|---|---|---|---|
| civis_api_polars_Ultim_BP_XI.json | https://vro.civis.net/LSV-Dash/api?context=api&context_type=polars&boatType=Ultim%20BP%20XI | Full VR polar `_id` 21 "Ultim BP XI" (7 sails, foil, hull, winch) | `_updatedAt` 2024-07-02 | High that this is VR data: it matches the ITYC copy exactly |
| ityc_export_Ultim_BP_XI.json | https://www.ityc.fr/data/export/Ultim_BP_XI.json | Same polar, JS-wrapped. The first sail uses key `_id`, the others `id` | 2024-07-02. Server Last-Modified 2026-10-25, so the file is regenerated regularly | High |
| civis_api_polars_multi_maxi_trimaran.json | https://vro.civis.net/LSV-Dash/api?context=api&context_type=polars&boatType=multi/maxi_trimaran | VR polar `_id` 6 "multi/maxi_trimaran" (older Ultim, solo) | 2024-07-02 | High |
| ityc_export_maxi_trimaran.json | https://www.ityc.fr/data/export/maxi_trimaran.json | Same `_id` 6, JS-wrapped, label "multi/maxi.trimaran" | 2024-07-02 | High |
| ityc_export_maxi_trimaran_x10percent.json | https://www.ityc.fr/data/export/maxi_trimaran_x10percent.json | VR `_id` 9 "Ultim' Crew" (about +10 % on `_id` 6) | 2024-01-30 | High |
| ityc_export_stamina.json | https://www.ityc.fr/data/export/stamina.json | Energy parameters: recovery, consumption, impact | unknown, 2026 copy | Medium (third party) |
| civis_api_races.json | https://vro.civis.net/LSV-Dash/api?context=api&context_type=races | 472 VR races with their boatId. Includes 797.1 Rhum Ultim = Ultim BP XI | list v416 | Medium-high |
| civis_api_boats.json | https://vro.civis.net/LSV-Dash/api?context=api&context_type=boats | Boat id list (no "Ultim" newer than BP XI) | v106 | Medium |
| civis_versions.json | https://vro.civis.net/polars/versions.json | Viewer app 6.1.8 | — | — |
| toxcct-github_multi_maxi_trimaran_v1.json | https://raw.githubusercontent.com/toxcct/VRPolarsChartData/d9cb1bd632025ed5c78596b837285a15f09b9178/data/boats/multi/maxi_trimaran_v1.json | `_id` 6, 2018-era format. Winch has only stdTimerSec/proTimerSec. Used for Route du Rhum 2018 | commit 2021-12-08 | High for history, obsolete |
| toxcct-github_multi_maxi_trimaran_v2.json | same repo and commit, …/maxi_trimaran_v2.json | `_id` 6 with lw/hw winch. Used for Route du Rhum 2022. Speed tables identical to v1 | commit 2021-12-08 | High for history, obsolete (456 Jib cells differ from 2024) |
| toxcct-github_multi_maxi_trimaran_x10percent.json | same repo and commit, …/maxi_trimaran_x10percent.json | `_id` 9 | commit 2021-05-20 | historical |
| toxcct-github_multi_maxi_trimaran_x4percent.json, toxcct-github_multi_ultim_macif.json | same repo and commit | Older variants (`_id` 6 with globalSpeedRatio 1.04; `_id` 12 MACIF) | 2021-01 | historical |
| toxcct-github_boats.json, toxcct-github_races.json, toxcct-github_VRPolarsChartData_README.md | same repo and commit | Boat and race lists up to Jan 2023 | — | historical |
| toxcct_boats_20251213.json, toxcct_races_20251213.json, toxcct_versions_20251213.json | http://web.archive.org/web/20251213090824id_/http://toxcct.free.fr/polars/data/boats.json (and races.json, versions.json) | Wayback copy of the dead toxcct.free.fr site (domain no longer resolves) | — | historical |
| toxcct_multi_maxi_trimaran_x10percent_id9_wayback20221206.json | http://web.archive.org/web/20221206125233id_/http://toxcct.free.fr/polars/data/boats/multi/maxi_trimaran_x10percent.json?_=1670331151973 | Byte-identical to the GitHub x10 file | 2021 | historical |
| zezo_races2.json | http://zezo.org/races2.json | Races open on zezo (no Rhum 2026 yet) | — | — |
| code/ityc-dashboard_js_dashboard.js.txt | https://raw.githubusercontent.com/7killer/ITYC-Dashboard/8338930cbd6a92fb0391b340d2d9ec33739b0873/js/dashboard.js | Code for penalties, energy, foil factor, bilinear interpolation. Boat-to-stamina table (6 Ultim Solo 1.5, 9 Ultim Crew 1.5, 21 Ultim BP XI 1.5) | commit 2026-10-21 | Medium (third-party implementation) |
| code/ityc-dashboard_js_stamina.js.txt | same repo, …/js/stamina.js | Same energy parameters as ityc_export_stamina.json | commit 2022-10-27 | Medium |
| code/ityc_polarDash.html.txt | https://www.ityc.fr/polarDash.html | Page that lists the ITYC export files | — | — |
| code/mak08-vrdashboard_dashboard.js.txt | https://raw.githubusercontent.com/mak08/VRDashboard/02181a460db01960eaa85183f43ad03b378a63c4/dashboard.js | Energy factor `2 - stamina/66.667`, citing virtualregatta.zendesk.com article 5402546102546 (Cloudflare returns 403, not readable) | commit 2023-11-09 | Medium. Its lw/hw fraction looks wrong |
| code/civis_polars_app.js.txt, code/civis_polars_reader.js.txt | https://vro.civis.net/polars/js/polars_app.js, …/polars_reader.js | Show which civis API URLs serve the lists and polars | v6.1.8/6.1.9 | — |
| code/phtheirichthys_src_main.rs.txt | https://raw.githubusercontent.com/phtheirichthys/phtheirichthys/b808716394d4b4562c6b581c160c46d2c46a7e41/src/main.rs | Embedded VR polar `_id` 19 Mod70 (`_updatedAt` 2024-01-30). Reference for the raw VR format | — | format reference only |

## Dead ends (nothing saved)
- toxcct.free.fr: the domain no longer exists, so only Wayback copies are saved.
- bitsailor.net/polars: 404. sailsphere.net/polars lists polars for another game, not VR.
- virtualregatta.zendesk.com energy article: HTTP 403 (Cloudflare), and no Wayback copy exists.
