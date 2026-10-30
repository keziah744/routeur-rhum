# Routeur météo Ultim — Route du Rhum 2026 (Virtual Regatta)

Routeur par isochrones maison : vent GFS 0,25° (NOAA), polaire VR « Ultim BP XI », côtes GSHHG,
parcours officiel 2026 (portes, zones interdites). Produit une feuille de route à saisir à la main dans
le programmateur de Virtual Regatta. Rien n'est injecté dans le jeu.

- Course VR : « Route du Rhum - Ultim » (race 797). Départ **dim. 1er nov. 2026 à 12:02 UTC** (13:02 Paris).
- Interface : `http://localhost:8765` sur le PC, `http://<IP-du-PC>:8765` sur le téléphone (même Wi-Fi).

## Installation (déjà faite sur ce PC)

```powershell
cd routeur-rhum
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m routeur masque      # côtes + zones interdites (GSHHG dans data\geo\sources)
.venv\Scripts\python.exe -m routeur meteo       # dernier cycle GFS (~130 requêtes, 5-8 min)
.venv\Scripts\python.exe -m routeur route       # route depuis la ligne de départ (~4 min)
.venv\Scripts\python.exe -m routeur serveur     # interface web
.venv\Scripts\python.exe -m routeur planifier   # tâche Windows : vérification GFS toutes les heures
```

## Commandes

| Commande | Effet |
|---|---|
| `meteo` | Récupère le dernier cycle GFS publié (rien si déjà en cache). |
| `route` | Calcule la route avec la prévision courante. Options : `--depart maintenant\|course\|2026-11-02T06:00Z`, `--position 46.2,-23.7`, `--porte 1`, `--gfs chemin\forecast.npz` (mode test hors ligne). |
| `cycle` | Ce que fait la tâche planifiée : météo, puis route seulement si la prévision a changé (ou position saisie). `--force` pour recalculer. |
| `ensemble` | 31 scénarios météo GEFS : une route par scénario, chaque route testée dans tous les scénarios, route la plus sûre (`route-safe.json`). `--force` pour recalculer. Environ 1 h de téléchargement + 20 min de calcul par cycle GEFS. |
| `expliquer` | Explication de la route en français par Claude (nécessite `ANTHROPIC_API_KEY`). |
| `serveur` | Interface + API locale (`--port`, `--hote 127.0.0.1` pour la limiter au PC). |
| `planifier` / `deplanifier` | Installe / retire les tâches Windows `RouteurRhum-cycle` (h:05) et `RouteurRhum-ensemble` (h:35). |
| `masque` | Reconstruit le masque (à relancer si on change la marge ou les zones). |

Tests : `.venv\Scripts\python.exe -m pytest -q` (vents synthétiques, chaîne météo hors ligne, géodésie).

## Pendant la course

1. Toutes les heures, la tâche vérifie si un nouveau cycle GFS (00/06/12/18 z, publié ~3 h 30 à 5 h après)
   est complet. Si oui : téléchargement ciblé (~260 Ko/échéance), validation, nouvelle route.
2. Après le départ, saisir la position lue dans le jeu (onglet **Météo** → *Position du bateau*) :
   sinon le routeur suppose que le bateau a suivi la route précédente.
3. Programmer dans VR les waypoints des 24-48 h à venir (onglet **Route**, tap sur une coordonnée = copie).
4. Le PC doit rester allumé et connecté. La tâche ne tourne que session ouverte.

## Version en ligne (GitHub Actions + Pages)

Le dépôt fait tourner le routeur dans le cloud, sans le PC :

- `.github/workflows/route.yml` : toutes les heures (h:05), nouvelle météo GFS -> nouvelle route, explication, page publiée.
- `.github/workflows/ensemble.yml` : toutes les heures (h:35), nouveau cycle GEFS ou nouvelle route -> 31 scénarios.
- `.github/workflows/position.yml` : formulaire « Run workflow » pour saisir la position lue dans le jeu.

Les résultats entre deux exécutions sont gardés dans le cache GitHub Actions ; la page est publiée sur GitHub Pages.
Clé Claude : secret `ANTHROPIC_API_KEY` du dépôt (Settings -> Secrets and variables -> Actions), à mettre soi-même.

## Explications par Claude (facultatif)

Le routeur demande à Claude (Opus 5.5) de raconter la route en quelques phrases : stratégie, ce qui a changé,
prochaines actions, fiabilité. Claude ne calcule rien : il lit les résultats. Coût : environ 3 centimes par
explication, 4 à 8 par jour. Le repli automatique vers un autre modèle en cas de refus (`fallbacks: "default"`)
est activé.

Pour l'activer, dans **ton** terminal (la clé ne doit jamais être écrite dans le projet ni envoyée dans le chat) :

```powershell
setx ANTHROPIC_API_KEY "ta-clé"
```

Puis fermer et rouvrir les terminaux. Les tâches planifiées la lisent à leur prochaine exécution.
Désactiver : `[explain] enabled = false` dans `config.toml`.

## Organisation

```
config.toml            configuration centrale (zone, échéances, options du bateau, pas de temps)
routeur/gfs.py         téléchargement NOMADS (+ secours AWS), cache, cycle courant
routeur/grib.py        décodage GRIB2 (ecCodes)
routeur/wind.py        interpolation bilinéaire espace + linéaire temps
routeur/polar.py       polaire VR, foils, coque, voiles, pénalités, énergie
routeur/geo.py         géodésie, masque terre/zones (tuiles fines départ/arrivée), segments
routeur/course.py      départ, portes orientées, arrivée
routeur/isochrones.py  moteur
routeur/roadmap.py     waypoints, changements de voile, contrôle, exports, comparaison
routeur/ensemble.py    scénarios GEFS : téléchargement, routes par scénario, simulateur, route la plus sûre
routeur/explain.py     explication en français par Claude (clé API facultative)
routeur/service.py     orchestration, verrou, fichiers publiés (web/data)
routeur/server.py      serveur local + API
web/                   interface (statique : fonctionne aussi sans serveur, en lecture seule)
data/                  polaire, parcours, masque, cache GFS ; sources brutes dans */sources/
docs/                  HYPOTHESES.md, FORMAT.md, DEPANNAGE.md
```

Voir **docs/HYPOTHESES.md** avant de faire confiance à une ETA.
