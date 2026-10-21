# POC – Moteur autonome Geo ZFE et Safety Physics

## Objectif
Cette preuve de concept démontre deux mécanismes indépendants :
1. **Geo / ZFE** : vérification rapide d'une position GPS par une Bounding Box, puis par l'algorithme Ray Casting (Point in Polygon). Si le point est dans le polygone, le programme affiche `[ALERT ZFE]`.
2. **Safety / Physics** : lecture des mesures d'accélération longitudinale, application d'un filtre médian pour atténuer les pics isolés, puis détection d'un freinage violent lorsque l'accélération filtrée est inférieure ou égale à `-2.5 G`. Le résultat est écrit dans `daily_score.json`.

> Hypothèse importante : les coordonnées GeoJSON sont en `[longitude, latitude]`. Le CSV doit fournir une accélération longitudinale déjà exprimée en G. Par convention, un freinage est une accélération longitudinale négative. Vérifier cette convention sur les données réelles avant utilisation.

## Prérequis
- Python 3.10 ou plus récent
- Aucune dépendance externe (bibliothèque standard Python uniquement)

## Lancer les tests en local
Dans un terminal, à la racine du projet :

```bash
python main.py
```

Le programme utilise par défaut :
- `lyon_polygon.json`
- `truck_gps.json`
- `accelerometer_data.csv`

Il affiche les alertes ZFE dans le terminal et crée `daily_score.json`.

### Lancer un seul module
```bash
python main.py --skip-safety
python main.py --skip-geo
```

### Modifier le seuil ou le filtre
```bash
python main.py --threshold-g 2.5 --filter-window 3
```

La taille du filtre doit être un entier impair positif.

## Formats d'entrée

### `lyon_polygon.json`
Format GeoJSON Polygon, ou liste de coordonnées `[longitude, latitude]`. Exemple :
```json
{
  "type": "Polygon",
  "coordinates": [[
    [4.80, 45.74],
    [4.90, 45.74],
    [4.90, 45.80],
    [4.80, 45.80],
    [4.80, 45.74]
  ]]
}
```

### `truck_gps.json`
Liste de points GPS (les clés `lon`/`lat` ou `longitude`/`latitude` sont acceptées) :
```json
[
  {"timestamp": "2026-10-21T08:00:00", "lon": 4.85, "lat": 45.77},
  {"timestamp": "2026-10-21T08:01:00", "lon": 4.95, "lat": 45.77}
]
```

### `accelerometer_data.csv`
En-têtes acceptés pour l'accélération longitudinale : `longitudinal_g`, `longitudinal_accel_g`, `ax_g`, `accel_x_g`, `x_g` ou `ax`. Les valeurs doivent être exprimées en G. `timestamp` est facultatif.

```csv
timestamp,longitudinal_g
2026-10-21T08:00:00,0.1
2026-10-21T08:00:01,-0.4
2026-10-21T08:00:02,-2.8
```

## Format de sortie `daily_score.json`
Le fichier contient la version du schéma, la date de génération, les paramètres du filtre, le nombre de mesures, le nombre de freinages violents détectés et le détail des événements. Il conserve également les mesures brutes et filtrées pour faciliter l'audit du POC.

## Pistes de réflexion et fonctionnement des algorithmes

### 1. Geo : Bounding Box + Ray Casting
- **Bounding Box** : calcule les limites min/max de longitude et latitude du polygone. Un point en dehors de ce rectangle est immédiatement rejeté.
- **Ray Casting** : uniquement pour les points dans la Bounding Box, trace conceptuellement un rayon horizontal depuis le point et compte les intersections avec les arêtes du polygone. Un nombre impair d'intersections indique que le point est à l'intérieur.
- **Intérêt** : la Bounding Box évite d'exécuter Ray Casting pour la majorité des positions éloignées de la ZFE, ce qui réduit le nombre de calculs.
- **Limites** : le POC traite un polygone simple et ne gère pas les trous (anneaux intérieurs) ni les géométries multi-polygones. La précision GPS et la qualité de la cartographie doivent être testées sur le terrain.

### 2. Safety : filtre médian + seuil
- **Filtrage** : le filtre médian sur une fenêtre de 3 échantillons atténue les pics isolés dus au bruit.
- **Seuil** : une mesure filtrée inférieure ou égale à `-2.5 G` est comptée comme freinage violent.
- **Pourquoi ce choix** : le filtrage réduit les faux positifs liés à un pic ponctuel, tandis que le seuil rend la règle explicite et testable.
- **Limites** : le seuil `2.5 G` doit être confirmé avec le métier et les données réelles. Si le CSV ne contient que les axes bruts d'un accéléromètre incluant la gravité, il faut d'abord calibrer l'orientation et retirer la composante gravitationnelle. Le POC utilise ici l'accélération longitudinale en G déjà préparée.

## Scénarios de test à présenter
1. Un point GPS à l'intérieur du polygone doit afficher `[ALERT ZFE]`.
2. Un point GPS à l'extérieur du rectangle Bounding Box ne doit pas déclencher Ray Casting ni d'alerte.
3. Un pic d'accélération isolé doit être atténué par le filtre médian.
4. Une accélération longitudinale filtrée à `-2.5 G` ou moins doit créer un événement dans `daily_score.json`.

## Publier le projet sur Git
Un dépôt distant GitHub/GitLab doit être créé par l'utilisateur (l'accès au compte n'est pas fourni dans cet environnement). Après création du dépôt, exécuter à la racine du dossier :

```bash
git init
git add main.py README.md lyon_polygon.json truck_gps.json accelerometer_data.csv
git commit -m "Add Geo ZFE and Safety Physics POC"
git branch -M main
git remote add origin https://github.com/VOTRE-UTILISATEUR/VOTRE-DEPOT.git
git push -u origin main
```

Remplacer l'URL d'exemple par celle du dépôt créé. Le lien à remettre dans la copie est alors l'URL réelle du dépôt.
