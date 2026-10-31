"""Optimisation des circuits de collecte.

Heuristique plus proche voisin puis amelioration 2-opt sur distances a vol d'oiseau
(haversine). Suffisant pour quelques dizaines d'arrets ; pour des distances routieres
reelles, brancher un moteur comme OSRM a la place de `haversine_km`.
"""
import math

EARTH_RADIUS_KM = 6371.0


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def _tour_length(points: list[tuple[float, float]], order: list[int]) -> float:
    # order commence et finit implicitement au depot (indice 0)
    path = [0, *order, 0]
    return sum(haversine_km(points[path[i]], points[path[i + 1]]) for i in range(len(path) - 1))


def optimize_route(depot: tuple[float, float], stops: list[tuple[float, float]]) -> dict:
    """Renvoie l'ordre de visite optimise (indices dans `stops`) et la distance totale aller-retour."""
    if not stops:
        return {"order": [], "distance_km": 0.0, "legs_km": []}
    points = [depot, *stops]
    remaining = set(range(1, len(points)))
    order, current = [], 0
    while remaining:
        nxt = min(remaining, key=lambda j: haversine_km(points[current], points[j]))
        order.append(nxt)
        remaining.remove(nxt)
        current = nxt

    improved = True
    while improved:
        improved = False
        for i in range(len(order) - 1):
            for k in range(i + 1, len(order)):
                candidate = order[:i] + order[i:k + 1][::-1] + order[k + 1:]
                if _tour_length(points, candidate) + 1e-9 < _tour_length(points, order):
                    order, improved = candidate, True

    path = [0, *order]
    legs = [haversine_km(points[path[i]], points[path[i + 1]]) for i in range(len(path) - 1)]
    return {
        "order": [i - 1 for i in order],
        "distance_km": round(_tour_length(points, order), 2),
        "legs_km": [round(x, 2) for x in legs],
    }
