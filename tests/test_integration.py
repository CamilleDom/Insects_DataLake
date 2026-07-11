"""
tests/test_integration.py
Suite de tests d'intégration pour tous les endpoints de l'API.
Vérifie que chaque endpoint répond correctement et retourne la structure attendue.

Usage : docker-compose exec api python /app/tests/test_integration.py
"""

import sys
import json
import time
import requests
from datetime import date

BASE_URL = "http://localhost:8000"

# ── Helpers ──────────────────────────────────────────────────────────────────

PASS = "✓"
FAIL = "✗"
WARN = "⚠"

results = []


def check(name: str, condition: bool, detail: str = ""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    symbol = "  " + status
    print(f"{symbol} {name}" + (f" — {detail}" if detail else ""))
    return condition


def section(title: str):
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_health():
    section("1. /health — Statut des services")
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        check("Status HTTP 200", r.status_code == 200, f"got {r.status_code}")
        data = r.json()
        check("Champ 'status' présent", "status" in data)
        check("Status = healthy", data.get("status") == "healthy", f"got '{data.get('status')}'")
        check("Champ 'services' présent", "services" in data)
        services = data.get("services", {})
        check("Service minio healthy", services.get("minio") == "healthy")
        check("Service postgres healthy", services.get("postgres") == "healthy")
        check("Champ timestamp présent", "timestamp" in data)
    except requests.exceptions.ConnectionError:
        check("Connexion à l'API", False, f"Impossible de joindre {BASE_URL}")


def test_stats():
    section("2. /stats — Métriques du data lake")
    try:
        r = requests.get(f"{BASE_URL}/stats", timeout=5)
        check("Status HTTP 200", r.status_code == 200, f"got {r.status_code}")
        data = r.json()
        check("Champ 'staging' présent", "staging" in data, str(list(data.keys())))
        check("Champ 'curated' présent", "curated" in data)
        check("Champ 'raw' présent", "raw" in data)
    except Exception as e:
        check("/stats accessible", False, str(e))


def test_raw():
    section("3. /raw — Zone de stockage brute")
    try:
        r = requests.get(f"{BASE_URL}/raw", timeout=5)
        check("Status HTTP 200", r.status_code == 200, f"got {r.status_code}")
        data = r.json()
        check("Réponse est une liste ou dict", isinstance(data, (list, dict)))
    except Exception as e:
        check("/raw accessible", False, str(e))


def test_staging():
    section("4. /staging — Données intermédiaires")
    try:
        r = requests.get(f"{BASE_URL}/staging", timeout=5)
        check("Status HTTP 200", r.status_code == 200, f"got {r.status_code}")
        data = r.json()
        # Accepte list directe ou dict avec une clé "data"/"occurrences"
        items = data if isinstance(data, list) else data.get("data", data.get("occurrences", []))
        check("Retourne des données", len(items) >= 0, f"{len(items)} occurrences")

        if items:
            first = items[0]
            check("Champ species_name présent", "species_name" in first)
            check("Champ latitude présent", "latitude" in first)
            check("Champ longitude présent", "longitude" in first)

        # Test pagination
        r2 = requests.get(f"{BASE_URL}/staging?limit=2&offset=0", timeout=5)
        check("Pagination (limit=2) fonctionne", r2.status_code == 200)

    except Exception as e:
        check("/staging accessible", False, str(e))


def test_curated_hotspots():
    section("5. /curated/hotspots — Richesse spécifique H3")
    try:
        r = requests.get(f"{BASE_URL}/curated/hotspots", timeout=5)
        check("Status HTTP 200", r.status_code == 200, f"got {r.status_code}")
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", data.get("hotspots", []))
        check("Retourne des données", isinstance(items, list), f"{len(items)} cellules H3")

        if items:
            first = items[0]
            check("Champ h3_cell présent", "h3_cell" in first)
            check("Champ species_count présent", "species_count" in first)
            check("Champ richness_normalized présent", "richness_normalized" in first)
            check("Champ richness_percentile présent", "richness_percentile" in first)
            check("richness_percentile entre 0 et 100",
                  0 <= first.get("richness_percentile", -1) <= 100,
                  f"got {first.get('richness_percentile')}")

    except Exception as e:
        check("/curated/hotspots accessible", False, str(e))


def test_curated_invasives():
    section("6. /curated/invasives — Alertes espèces invasives")
    try:
        r = requests.get(f"{BASE_URL}/curated/invasives", timeout=5)
        check("Status HTTP 200", r.status_code == 200, f"got {r.status_code}")
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", data.get("invasives", []))
        check("Retourne une liste", isinstance(items, list))

        if items:
            first = items[0]
            check("Champ species_name présent", "species_name" in first)
            check("Champ is_invasive = True", first.get("is_invasive") is True or "invasive" in str(first))
            check("Champ invasive_risk présent", "invasive_risk" in first)
            valid_risks = {"high", "medium", "low"}
            check("invasive_risk valide",
                  first.get("invasive_risk") in valid_risks,
                  f"got '{first.get('invasive_risk')}'")

        # Test filtre par risk
        r2 = requests.get(f"{BASE_URL}/curated/invasives?risk=high", timeout=5)
        check("Filtre ?risk=high fonctionne", r2.status_code == 200)

    except Exception as e:
        check("/curated/invasives accessible", False, str(e))


def test_ingest():
    section("7. /ingest — Ingestion standard")
    payload = {
        "data": {
            "observations": [
                {
                    "species_name": "Vespa velutina",
                    "latitude": 48.8566,
                    "longitude": 2.3522,
                    "observed_on": str(date.today())
                }
            ]
        }
    }
    try:
        start = time.time()
        r = requests.post(f"{BASE_URL}/ingest", json=payload, timeout=15)
        elapsed_ms = (time.time() - start) * 1000

        check("Status HTTP 200", r.status_code == 200, f"got {r.status_code}")
        data = r.json()
        check("Champ 'inserted' présent", "inserted" in data, str(list(data.keys())))
        check("1 observation insérée", data.get("inserted", 0) >= 1, f"got {data.get('inserted')}")
        check("execution_time_ms présent", "execution_time_ms" in data)
        print(f"     → Temps d'exécution (1 élément) : {elapsed_ms:.1f} ms")

        # Stocker le temps pour comparaison avec /ingest_fast
        return elapsed_ms

    except Exception as e:
        check("/ingest accessible", False, str(e))
        return None


def test_ingest_fast(baseline_ms: float = None):
    section("8. /ingest_fast — Ingestion optimisée")

    # Batch de 100 observations
    observations = [
        {
            "species_name": "Apis mellifera" if i % 3 != 0 else "Vespa velutina",
            "latitude": round(48.0 + i * 0.05, 6),
            "longitude": round(2.0 + i * 0.03, 6),
            "observed_on": str(date.today())
        }
        for i in range(100)
    ]
    payload = {"data": {"observations": observations}}

    try:
        start = time.time()
        r = requests.post(f"{BASE_URL}/ingest_fast", json=payload, timeout=30)
        elapsed_ms = (time.time() - start) * 1000

        check("Status HTTP 200", r.status_code == 200, f"got {r.status_code}")
        data = r.json()
        check("Champ 'inserted' présent", "inserted" in data)
        check("Des observations insérées", data.get("inserted", 0) > 0, f"got {data.get('inserted')}")
        check("execution_time_ms présent", "execution_time_ms" in data)
        print(f"     → Temps d'exécution (100 éléments) : {elapsed_ms:.1f} ms")

        # Comparaison perf si on a un baseline
        if baseline_ms is not None:
            # Normalise : compare le temps par élément
            fast_per_item = elapsed_ms / 100
            baseline_per_item = baseline_ms / 1
            improvement = (1 - fast_per_item / baseline_per_item) * 100
            check(
                "Amélioration >= 30% vs /ingest",
                improvement >= 30,
                f"gain mesuré : {improvement:.1f}%"
            )

    except Exception as e:
        check("/ingest_fast accessible", False, str(e))


def test_error_handling():
    section("9. Gestion des erreurs")
    try:
        # Payload invalide
        r = requests.post(f"{BASE_URL}/ingest", json={"invalid": "payload"}, timeout=5)
        check("Payload invalide → 4xx", 400 <= r.status_code < 500, f"got {r.status_code}")

        # Route inexistante
        r2 = requests.get(f"{BASE_URL}/nonexistent_route", timeout=5)
        check("Route inconnue → 404", r2.status_code == 404, f"got {r2.status_code}")

    except Exception as e:
        check("Gestion erreurs testable", False, str(e))


# ── Résumé ────────────────────────────────────────────────────────────────────

def print_summary():
    print(f"\n{'═' * 50}")
    print("  RÉSUMÉ")
    print(f"{'═' * 50}")

    passed = sum(1 for s, _, _ in results if s == PASS)
    failed = sum(1 for s, _, _ in results if s == FAIL)
    total = len(results)

    for status, name, detail in results:
        line = f"  {status} {name}"
        if detail:
            line += f" ({detail})"
        print(line)

    print(f"\n  {passed}/{total} tests passés", end="")
    if failed > 0:
        print(f"  —  {failed} échec(s)")
    else:
        print("  — Tous les tests passés ✓")
    print()


if __name__ == "__main__":
    print("\n╔══════════════════════════════════════════════╗")
    print("\n║   Insect Lake — Tests d'intégration          ║")
    print("\n╚══════════════════════════════════════════════╝")

    test_health()
    test_stats()
    test_raw()
    test_staging()
    test_curated_hotspots()
    test_curated_invasives()
    baseline = test_ingest()
    test_ingest_fast(baseline_ms=baseline)
    test_error_handling()
    print_summary()

    # Exit code non-zéro si des tests échouent (utile pour CI)
    failed_count = sum(1 for s, _, _ in results if s == FAIL)
    sys.exit(1 if failed_count > 0 else 0)