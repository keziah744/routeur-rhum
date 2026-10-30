# Format des fichiers publiés (web/data/)

Toutes les heures sont en UTC, au format ISO 8601 (`2026-11-01T12:02Z`). Coordonnées en degrés décimaux,
ouest et sud négatifs. Vitesses en nœuds, angles en degrés.

## route.json — `"format": "routeur-rhum/route@1"`

| Champ | Contenu |
|---|---|
| `computed_at` | heure du calcul |
| `race`, `boat`, `polar_file`, `options`, `sail_names` | contexte (index de voile → nom) |
| `gfs_cycle`, `gfs_run`, `wind_file` | prévision utilisée (`2026102512` = 25/10 12z) |
| `start_source`, `start`, `start_time` | d'où part le calcul (ligne de départ, position saisie, estimée) |
| `arrived`, `eta`, `duration_h`, `distance_nm` | résultat |
| `beyond_forecast_from` | heure à partir de laquelle la route sort de la prévision (sinon `null`) |
| `check_waypoints` | contrôle : `planned_h`, `simulated_h`, `loss_pct`, `worst_legs` |
| `waypoints[]` | `n`, `lat`, `lon`, `t`, `heading` (cap loxodromique vers le suivant), `twa` (+ tribord / − bâbord), `tws`, `twd`, `sail`, `speed`, `reason`, `beyond_forecast` |
| `sail_changes[]` | `t`, `lat`, `lon`, `sail_from`, `sail_to`, `gain_pct`, `twa`, `tws` |
| `track[]` | trace complète : `[lat, lon, t, index_voile, tws, twa, vitesse]` |
| `gates[]`, `gates_passed_track[]` | portes du parcours et porte visée à chaque point de trace |
| `isochrones[]` | `{t (epoch s), lat[], lon[]}` toutes les 6 h, allégées pour l'affichage |
| `comparison` | écart avec la route précédente : `eta_delta_h`, `max_deviation_nm`, `mean_deviation_nm`, `previous_track`, `previous_waypoints` |
| `stats` | `steps`, `candidates`, `compute_s` |

`route-prev.json` : la route précédente, même format.

## feuille-de-route.csv

Séparateur `;`, UTF-8 avec BOM (ouvre directement dans Excel) :
`n;heure_utc;latitude;longitude;cap;twa;tws_kt;twd;voile;vitesse_kt;motif`.

## feuille-de-route.gpx

GPX 1.1, une `<rte>` avec un `<rtept>` par waypoint (nom `WP00`, heure, voile et motif en description).

## status.json / weather-status.json

- `status.json` : `weather` (cycle, âge en heures, `stale` si > 9 h, `incomplete`), `route` (état, message, durée), `race`.
- `weather-status.json` : dernière vérification GFS (`state` = à jour / téléchargement / ok / erreur, `done`/`total`, `message`).

## wind.json — `"format": "routeur-rhum/wind@1"`

Champ allégé pour la carte : grille 1° (`lat0`, `lon0`, `step`, `nlat`, `nlon`), une trame toutes les 6 h.
`frames[].uv` = base64 d'un tableau int8 : `nlat×nlon` valeurs de U puis autant de V, en unités de `scale_ms` (0,5 m/s).
