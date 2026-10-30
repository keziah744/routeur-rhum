# Dépannage

Journal : `logs\routeur.log` (rotation 2 Mo × 5). Commencer toujours par là.

| Symptôme | Cause probable | Que faire |
|---|---|---|
| Pastille météo orange « ancienne » (> 9 h) | La tâche ne tourne pas (PC en veille, session fermée) ou NOAA en retard | `schtasks /Query /TN RouteurRhum-cycle` ; lancer `python -m routeur cycle` à la main et lire le journal |
| « liste NOMADS … 403 » dans le journal | Normal pour un cycle en cours de publication | Rien : le cycle précédent est utilisé |
| 403 sur **tous** les cycles, ou réponse « Over Rate Limit » | NOMADS bloque l'adresse IP (trop de requêtes) | Le secours AWS prend le relais automatiquement ; attendre, ne pas relancer en boucle ; augmenter `request_pause_s` |
| `GribError … non GRIB` | Page d'erreur reçue à la place d'un fichier | Relancé automatiquement, puis secours AWS |
| « aucun cycle récent assez publié » | Retard de NOAA ou coupure réseau | La dernière prévision valide reste utilisée ; vérifier l'accès Internet du PC |
| « route bloquée : aucun progrès vers … » | Le front ne trouve pas de passage (porte mal placée, marge trop forte, zone interdite fermant le passage) | Vérifier la porte dans `data\course\route-du-rhum-2026.json` et la carte ; réduire `margin_nm` de la tuile concernée puis `python -m routeur masque` |
| « le point de départ … est dans un obstacle » | Position saisie sur la terre ou dans la marge | Corriger la position (format `46°12,5 N`, `23°40,1 W`, ou décimal avec ouest négatif) |
| « un calcul est déjà en cours » | Tâche planifiée et bouton en même temps | Normal : attendre la fin (3-5 min) |
| Le téléphone n'accède pas à l'interface | Pas sur le même Wi-Fi, pare-feu Windows | Lancer `python -m routeur serveur` (écoute 0.0.0.0:8765), autoriser Python sur les réseaux **privés** quand Windows le demande, ouvrir `http://<IP du PC>:8765` (`ipconfig` → adresse IPv4) |
| La copie de coordonnées ne marche pas sur le téléphone | Navigateur restrictif en http | Appui long sur la coordonnée pour la sélectionner |
| ETA qui saute de plusieurs heures | Nouveau cycle GFS : normal au-delà de 5 jours | Comparer avec la carte « Par rapport à la route précédente » |

## Tester sans réseau

```powershell
.venv\Scripts\python.exe -m pytest -q                              # tests (réseau simulé)
.venv\Scripts\python.exe -m routeur route --gfs data\gfs\2026102512\forecast.npz
```

## Remettre à zéro

- Prévisions : supprimer `data\gfs\<cycle>` (ou tout `data\gfs`) puis `python -m routeur meteo`.
- Position saisie : supprimer `data\position.json`.
- Tâche : `python -m routeur deplanifier`.
