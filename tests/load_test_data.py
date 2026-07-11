"""
Charge des données de test dans staging.occurrences
Usage :
docker-compose exec api python /tests/load_test_data.py
"""

import sys
import uuid
from datetime import date

sys.path.insert(0, "/app")

from db import get_db_connection  # ton module DB existant

# Données de test
TEST_OBSERVATIONS = [
    ("Vespa velutina", 48.8566, 2.3522),
    ("Vespa velutina", 45.7640, 4.8357),
    ("Harmonia axyridis", 43.2965, 5.3698),
    ("Apis mellifera", 47.3220, 5.0415),
    ("Bombus terrestris", 48.5734, 7.7521),
    ("Lucanus cervus", 44.8378, -0.5792),
    ("Mantis religiosa", 43.6047, 1.4442),
    ("Papilio machaon", 47.9029, 1.9093),
    ("Solenopsis invicta", 43.1242, 5.9280),
    ("Carabus auratus", 50.6292, 3.0573),
]


def load_test_data():
    conn = get_db_connection()
    cursor = conn.cursor()

    inserted = 0
    skipped = 0

    today = date.today()

    for i, (species, lat, lon) in enumerate(TEST_OBSERVATIONS):

        obs_id = str(uuid.uuid4())

        cursor.execute(
            """
            INSERT INTO staging.occurrences
                (id, species_name, latitude, longitude, observed_on, quality_grade, source)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                obs_id,
                species,
                lat + i * 0.001,
                lon + i * 0.001,
                today,
                "research",
                "test",
            ),
        )

        if cursor.rowcount > 0:
            inserted += 1
        else:
            skipped += 1

    conn.commit()
    cursor.close()
    conn.close()

    print(f"✓ Test data loaded: {inserted} inserted, {skipped} skipped")


if __name__ == "__main__":
    load_test_data()