#!/usr/bin/env python3
"""POC autonome : détection ZFE (Geo) et freinage violent (Physics)."""
import argparse
import csv
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_polygon(data):
    """Accepte un GeoJSON Polygon ou une liste de coordonnées [lon, lat]."""
    if isinstance(data, dict):
        if data.get("type") == "Feature":
            data = data.get("geometry", {})
        if data.get("type") == "FeatureCollection":
            features = data.get("features", [])
            if not features:
                raise ValueError("FeatureCollection vide")
            data = features[0].get("geometry", {})
        if data.get("type") == "Polygon":
            rings = data.get("coordinates", [])
            if not rings:
                raise ValueError("Polygon sans coordonnées")
            return [(float(p[0]), float(p[1])) for p in rings[0]]
        # Formats personnalisés fréquents
        for key in ("coordinates", "polygon", "points"):
            if key in data:
                return extract_polygon(data[key])
    if isinstance(data, list) and data and isinstance(data[0], list):
        # Accepte [[lon, lat], ...] ou [[[lon,lat],...]] (anneau GeoJSON)
        coords = data
        if coords and isinstance(coords[0], list) and coords[0] and isinstance(coords[0][0], list):
            coords = coords[0]
        return [(float(p[0]), float(p[1])) for p in coords]
    raise ValueError("Format polygonal non reconnu. Utiliser GeoJSON Polygon ou [[lon, lat], ...].")


def extract_gps_points(data):
    """Accepte un point, une liste de points ou {'points': [...]}."""
    if isinstance(data, dict):
        if "features" in data:  # GeoJSON FeatureCollection
            points = []
            for feature in data["features"]:
                geom = feature.get("geometry") or {}
                if geom.get("type") == "Point":
                    lon, lat = geom.get("coordinates", [None, None])[:2]
                    points.append({"lon": lon, "lat": lat, "timestamp": (feature.get("properties") or {}).get("timestamp")})
            return points
        if "points" in data:
            data = data["points"]
        elif "gps" in data:
            data = data["gps"]
        elif "lon" in data and "lat" in data:
            return [data]
        elif "longitude" in data and "latitude" in data:
            return [data]
    if not isinstance(data, list):
        raise ValueError("truck_gps.json doit contenir un point ou une liste de points.")
    points = []
    for p in data:
        if not isinstance(p, dict):
            continue
        lon = p.get("lon", p.get("longitude"))
        lat = p.get("lat", p.get("latitude"))
        if lon is not None and lat is not None:
            points.append({"lon": float(lon), "lat": float(lat), "timestamp": p.get("timestamp")})
    return points


def point_in_polygon_ray_casting(point, polygon):
    """Ray Casting : compte les intersections d'un rayon horizontal avec le polygone."""
    x, y = point
    inside = False
    n = len(polygon)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        # Le test strict sur les latitudes évite de compter deux fois les sommets.
        crosses = ((yi > y) != (yj > y))
        if crosses:
            x_intersection = (xj - xi) * (y - yi) / ((yj - yi) or 1e-15) + xi
            if x < x_intersection:
                inside = not inside
        j = i
    return inside


def check_zfe(polygon, gps_points):
    """Bounding Box d'abord, puis Ray Casting uniquement pour les points candidats."""
    min_lon = min(p[0] for p in polygon)
    max_lon = max(p[0] for p in polygon)
    min_lat = min(p[1] for p in polygon)
    max_lat = max(p[1] for p in polygon)
    results = []
    for p in gps_points:
        lon, lat = float(p["lon"]), float(p["lat"])
        in_bbox = min_lon <= lon <= max_lon and min_lat <= lat <= max_lat
        inside = in_bbox and point_in_polygon_ray_casting((lon, lat), polygon)
        results.append({
            "timestamp": p.get("timestamp"),
            "lon": lon,
            "lat": lat,
            "inside_bbox": in_bbox,
            "inside_zfe": inside,
        })
        if inside:
            print(f"[ALERT ZFE] Entrée/détection dans la ZFE — GPS=({lon:.6f}, {lat:.6f})"
                  + (f" — timestamp={p.get('timestamp')}" if p.get("timestamp") else ""))
    if not any(r["inside_zfe"] for r in results):
        print("[INFO] Aucun point GPS détecté à l'intérieur de la ZFE.")
    return results


def parse_acceleration(row):
    """Retourne l'accélération longitudinale en G, selon les noms de colonnes reconnus."""
    aliases = ("longitudinal_g", "longitudinal_accel_g", "ax_g", "accel_x_g", "x_g", "ax")
    lower = {k.strip().lower(): v for k, v in row.items() if k is not None}
    for name in aliases:
        if lower.get(name, "") not in ("", None):
            return float(lower[name])
    raise ValueError("Colonne longitudinale absente. Utiliser longitudinal_g ou ax_g (valeurs en G).")


def median_filter(values, window=3):
    """Filtre médian glissant qui atténue les pics isolés sans effacer les événements persistants."""
    out = []
    half = window // 2
    for i in range(len(values)):
        segment = values[max(0, i-half):min(len(values), i+half+1)]
        out.append(statistics.median(segment))
    return out


def analyze_safety(csv_path, output_path, threshold_g=2.5, window=3):
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV vide ou sans en-têtes.")
        for index, row in enumerate(reader):
            value = parse_acceleration(row)
            timestamp = row.get("timestamp") or row.get("time") or row.get("datetime") or str(index)
            rows.append({"timestamp": timestamp, "raw_g": value})
    if not rows:
        raise ValueError("Aucune mesure d'accélération dans le CSV.")
    filtered = median_filter([r["raw_g"] for r in rows], window)
    events = []
    for i, row in enumerate(rows):
        row["filtered_g"] = round(filtered[i], 4)
        row["violent_braking"] = filtered[i] <= -abs(threshold_g)
        # Les données peuvent aussi utiliser une convention de signe inversée.
        # Par défaut, freinage = accélération longitudinale négative.
        if row["violent_braking"]:
            events.append({
                "timestamp": row["timestamp"],
                "raw_g": row["raw_g"],
                "filtered_g": round(filtered[i], 4),
                "type": "FREINAGE_VIOLENT",
            })
    score = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_file": Path(csv_path).name,
        "method": {
            "filter": f"median_glissant_{window}",
            "threshold_g": -abs(threshold_g),
            "unit": "G",
            "event_rule": "acceleration_longitudinale_filtree <= -threshold_g",
        },
        "summary": {
            "samples_count": len(rows),
            "violent_braking_count": len(events),
            "violent_braking_detected": bool(events),
        },
        "events": events,
        "measurements": rows,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(score, f, ensure_ascii=False, indent=2)
    print(f"[SAFETY] {len(events)} freinage(s) violent(s) détecté(s).")
    print(f"[SAFETY] Résultat écrit dans : {output_path}")
    return score


def main():
    parser = argparse.ArgumentParser(description="POC moteur Geo ZFE + moteur Safety Physics")
    parser.add_argument("--polygon", default="lyon_polygon.json", help="Polygone ZFE au format JSON/GeoJSON")
    parser.add_argument("--gps", default="truck_gps.json", help="Positions GPS du camion au format JSON")
    parser.add_argument("--accelerometer", default="accelerometer_data.csv", help="Mesures longitudinales en G")
    parser.add_argument("--output", default="daily_score.json", help="Fichier de sortie Safety JSON")
    parser.add_argument("--threshold-g", type=float, default=2.5, help="Seuil de freinage violent en G")
    parser.add_argument("--filter-window", type=int, default=3, help="Taille impaire du filtre médian")
    parser.add_argument("--skip-geo", action="store_true", help="Ne lancer que le moteur Safety")
    parser.add_argument("--skip-safety", action="store_true", help="Ne lancer que le moteur Geo")
    args = parser.parse_args()

    if args.filter_window < 1 or args.filter_window % 2 == 0:
        parser.error("--filter-window doit être un entier impair supérieur ou égal à 1")

    if not args.skip_geo:
        polygon = extract_polygon(load_json(args.polygon))
        gps_points = extract_gps_points(load_json(args.gps))
        check_zfe(polygon, gps_points)
    if not args.skip_safety:
        analyze_safety(args.accelerometer, args.output, args.threshold_g, args.filter_window)


if __name__ == "__main__":
    main()
