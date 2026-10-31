"""Optimisation des circuits de collecte.

Heuristique plus proche voisin puis amelioration 2-opt sur distances a vol d'oiseau
(haversine), avec matrice de distances et calcul incremental du gain : rapide jusqu'a
plusieurs centaines d'arrets. Pour des distances routieres reelles, remplacer la matrice
par celle d'un moteur comme OSRM.
"""
import math

EARTH_RADIUS_KM = 6371.0


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def optimize_route(depot: tuple[float, float], stops: list[tuple[float, float]], max_passes: int = 50) -> dict:
    """Renvoie l'ordre de visite optimise (indices dans `stops`) et la distance totale aller-retour."""
    if not stops:
        return {"order": [], "distance_km": 0.0, "legs_km": []}
    pts = [depot, *stops]
    n = len(pts)
    dist = [[haversine_km(pts[i], pts[j]) for j in range(n)] for i in range(n)]

    # 1. Plus proche voisin depuis le depot
    remaining = set(range(1, n))
    path, current = [0], 0
    while remaining:
        nxt = min(remaining, key=lambda j: dist[current][j])
        path.append(nxt)
        remaining.remove(nxt)
        current = nxt
    path.append(0)

    # 2. 2-opt : inverse un segment si cela raccourcit le circuit
    for _ in range(max_passes):
        improved = False
        for i in range(1, len(path) - 2):
            for k in range(i + 1, len(path) - 1):
                a, b, c, d = path[i - 1], path[i], path[k], path[k + 1]
                if dist[a][c] + dist[b][d] - dist[a][b] - dist[c][d] < -1e-9:
                    path[i:k + 1] = path[i:k + 1][::-1]
                    improved = True
        if not improved:
            break

    legs = [dist[path[i]][path[i + 1]] for i in range(len(path) - 2)]  # sans le retour au depot
    total = sum(dist[path[i]][path[i + 1]] for i in range(len(path) - 1))
    return {
        "order": [p - 1 for p in path[1:-1]],
        "distance_km": round(total, 2),
        "legs_km": [round(x, 2) for x in legs],
    }
