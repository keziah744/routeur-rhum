# Hypothèses, limites de précision et incertitudes

Légende : **VÉRIFIÉ** = contrôlé sur une source ou par un test ; **SUPPOSÉ** = choix raisonnable non confirmé.

## Une route calculée n'est jamais « l'optimale »

- Le moteur est discret : pas de temps de 15 min au départ, 1 h au large, 10 min puis 2 min près des marques ;
  éventail de TWA tous les 3° ; un point gardé par secteur d'environ 4 milles. Une meilleure route peut passer
  entre deux mailles.
- Le GFS 0,25° est une prévision : au-delà de 5 jours, l'ETA peut bouger d'un jour d'un cycle à l'autre.
  Après la dernière échéance (+384 h), la dernière prévision est maintenue et la feuille de route le signale.
- Contrôle mesuré (25/10, GFS 12z) : en resimulant chaque leg de la feuille de route au pas de 5 min,
  la perte est de **0,6 %** (178,3 h simulées pour 177,3 h prévues). VÉRIFIÉ.
- Un bateau qui prend du retard rencontre une autre météo : il faut recalculer, pas suivre une vieille route.

## Scénarios météo (ensemble GEFS)

- NOAA GEFS 0,5° : 31 versions de la même prévision (contrôle + 30 perturbées), pas de 6 h jusqu'à +384 h. VÉRIFIÉ
  (disponibilité et téléchargement filtré, 25/10).
- Pour chaque scénario, le moteur calcule la route optimale (réglages plus grossiers : TWA tous les 5°, secteurs de
  8 milles, pas de 2 h au large). Puis **chaque route candidate** (route GFS + les 31 routes) est rejouée dans
  **chaque scénario** par un simulateur qui suit les waypoints, louvoie et empanne aux angles de meilleure VMG,
  avec voile auto, pénalités et énergie. Route conseillée = meilleure arrivée médiane, départagée par le P90.
- Ce que ça apporte : une route qui reste bonne si la prévision se trompe, et une fourchette d'arrivée honnête.
  Ce que ça ne fait pas : prévoir la météo mieux que la NOAA. VR utilise le GFS déterministe : quand les scénarios
  divergent, la route GFS peut quand même s'avérer la bonne dans le jeu.
- Le simulateur ignore la terre (les legs des candidats ont été vérifiés sur leur propre route) : en louvoyage près
  des côtes, l'évaluation peut être un peu optimiste. SUPPOSÉ acceptable au large.
- Cycle GEFS utilisé = le plus récent publié **jusqu'à +384 h pour les 31 membres** : souvent 6 h de retard sur le GFS.

## Explications par Claude

- Texte rédigé par Claude Opus 5.5 à partir des résultats chiffrés (pas de la trace complète) : ~6 000 jetons
  envoyés, quelques centimes par explication. Claude peut mal interpréter un système météo : il lui est demandé de
  le présenter comme une interprétation. L'appel réel n'a pas encore été testé faute de clé (26/10).

## Polaire (data/polar/ultim-bp-xi.json)

- Polaire VR `_id` 21 « Ultim BP XI », mise à jour VR du 02/07/2024, celle de la course VR 797. Deux copies
  identiques (civis, ityc.fr), voir `data/polar/sources/SOURCES.md`. VÉRIFIÉ par comparaison des sources,
  **pas** contre le jeu lui-même (il faut être connecté). VR peut changer la polaire avant ou pendant la course.
- Ce n'est pas la polaire 2018 : les anciennes (`_id` 6, 2018/2021/2024, et `_id` 9 Ultim Crew) sont gardées
  dans `sources/` pour référence.
- 7 voiles : Jib, Spi, Staysail, LightJib, Code0, HeavyGnk, LightGnk. Staysail/HeavyGnk = option « heavy »,
  LightJib/LightGnk = « light », Code0 = « reach ». Options cochées dans `config.toml` [boat] (pack complet par défaut).
- Vitesse = interpolation bilinéaire du tableau (TWA, TWS) ; foils : ×1,04 dans TWA 80-160° et TWS 16-35 kt,
  rampe linéaire sur 10° / 5 kt (méthode des outils communautaires, SUPPOSÉ) ; coque ×1,003.
- Le tableau brut contient des valeurs étranges (vitesse non nulle à TWA 20°, creux à certains vents). Gardées
  telles quelles : ce sont celles du jeu.
- Remplacer la polaire : déposer un autre JSON au format VR et changer `[polar] file`. Aucun code à modifier.

## Pénalités et énergie

- Virement / empannage : 180 s (≤ 10 kt) à 300 s (≥ 30 kt) ; changement de voile 300 à 480 s. Vitesse ×0,7
  avec le treuil pro, ×0,5 sans. Valeurs VÉRIFIÉES dans la polaire ; **interpolation linéaire entre 10 et 30 kt
  SUPPOSÉE** (VR ne publie pas la courbe ; ITYC utilise un cosinus).
- Énergie (« stamina ») : modèle ITYC, **non officiel**. Durée × (2 à 0 % … 0,5 à 100 %) ; coût 10 points par
  virement/empannage, 20 par changement de voile, × facteur vent (1 à 2) × 1,5 pour l'Ultim ; récupération 1 point
  toutes les 5 à 15 min selon le vent. Départ supposé à 100 %.
- Changement de voile : seulement si la meilleure voile dépasse la voile actuelle de plus de
  `autoSailChangeTolerance` (1,4 %, VR) et du seuil `sail_change_min_gain_pct` (config). Comme la voile auto du jeu.

## Météo

- NOAA GFS 0,25°, vent à 10 m (UGRD/VGRD), pas de 3 h jusqu'à +384 h, zone 5-60°N / 85°W-5°E. VÉRIFIÉ.
- **Virtual Regatta n'utilise pas forcément ces fichiers à l'identique** (résolution, délai de mise en ligne,
  interpolation temporelle propre au jeu). Le vent du jeu peut différer de quelques nœuds et degrés. SUPPOSÉ.
- Interpolation : bilinéaire sur U et V, linéaire dans le temps ; vitesse évaluée au milieu de chaque segment.

## Géographie et parcours

- Côtes GSHHG 2.3.7 pleine résolution, marge de sécurité 0,5 mille (0,1 mille autour de la Guadeloupe pour
  laisser le passage entre la bouée de Basse-Terre et la côte). **Le trait de côte du jeu n'est pas GSHHG** :
  vérifier visuellement dans VR les passages près des caps, d'Ouessant et en Guadeloupe.
- Parcours : instructions de course 2026 avec avenants 1 et 2 (`data/course/COURSE-NOTES.md`). Départ, porte Fréhel,
  Tête à l'Anglais à bâbord, bouée Basse-Terre à tribord, Saintes à tribord, bouée d'atterrissage PP, ligne
  d'arrivée : positions VÉRIFIÉES ; leur traduction en portes orientées est SUPPOSÉE.
- 21 zones interdites (rails de navigation, parcs éoliens, zones cétacés…) gravées comme obstacles. VÉRIFIÉ sur
  les IC. **Les zones et portes propres à la course VR 797 ne sont pas publiques** : à comparer dans le jeu.
- La ligne de départ est « approximative » dans les IC (positions définitives 48 h avant) : mettre à jour
  `data/course/route-du-rhum-2026.json` si elle bouge.

## Waypoints

- Simplification Douglas-Peucker (3 milles), puis découpe de tout leg simplifié qui touche un obstacle ou qui,
  resimulé, perd plus de 2 % ou 2 min. Les virements, empannages et portes sont toujours des waypoints.
- Le cap affiché est loxodromique (cap constant) ; en mode waypoint, le jeu peut suivre l'orthodromie : écart
  négligeable sur des legs de quelques dizaines de milles.
- Le nombre de waypoints acceptés par le programmateur VR n'est pas connu ici : programmer les 24-48 h à venir.
