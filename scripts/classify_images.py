#!/usr/bin/env python3
"""
Pipeline de classification d'images : staging -> curated.image_classifications

Traite les observations possédant une photo (staging.occurrences.photo_url)
et non encore classifiées, par petits lots (l'inférence CPU est plus lente
qu'une simple requête SQL, on évite donc de tout traiter d'un coup dans un
DAG horaire).

Usage :
    python classify_images.py [limit]
"""

import logging
import os
import sys

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.dirname(__file__))
from image_classifier import classify_image

logger = logging.getLogger(__name__)

DEFAULT_BATCH_LIMIT = 20


class ImageClassificationPipeline:
    """Orchestration de la classification CNN pour la zone curated"""

    def __init__(self, pg_host, pg_port, pg_user, pg_password, pg_db):
        self.conn = psycopg2.connect(
            host=pg_host, port=pg_port, user=pg_user,
            password=pg_password, database=pg_db
        )
        logger.info("Connecté à PostgreSQL")

    def close(self):
        if self.conn:
            self.conn.close()

    def get_unclassified_observations(self, limit=DEFAULT_BATCH_LIMIT):
        """Récupère les observations avec photo, pas encore classifiées"""
        cursor = self.conn.cursor(cursor_factory=RealDictCursor)
        cursor.execute("""
            SELECT o.id, o.species_name, o.photo_url
            FROM staging.occurrences o
            LEFT JOIN curated.image_classifications c
                ON c.occurrence_id = o.id
            WHERE o.photo_url IS NOT NULL
              AND c.occurrence_id IS NULL
            ORDER BY o.ingested_at DESC
            LIMIT %s
        """, (limit,))
        rows = cursor.fetchall()
        cursor.close()
        return rows

    def run(self, limit=DEFAULT_BATCH_LIMIT):
        observations = self.get_unclassified_observations(limit)
        logger.info(f"{len(observations)} observation(s) à classifier")

        classified, errors = 0, 0
        cursor = self.conn.cursor()

        for obs in observations:
            try:
                result = classify_image(obs['photo_url'])
                if result is None:
                    errors += 1
                    continue

                cursor.execute("""
                    INSERT INTO curated.image_classifications
                    (occurrence_id, species_name, image_url, predicted_class,
                     confidence, is_likely_insect, top5_predictions)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (occurrence_id) DO NOTHING
                """, (
                    obs['id'], obs['species_name'], obs['photo_url'],
                    result['predicted_class'], result['confidence'],
                    result['is_likely_insect'], str(result['top5'])
                ))
                self.conn.commit()
                classified += 1
                logger.info(
                    f"{obs['id']} -> {result['predicted_class']} "
                    f"({result['confidence']:.1%}, insecte={result['is_likely_insect']})"
                )
            except Exception as e:
                self.conn.rollback()
                logger.error(f"Échec classification {obs['id']}: {e}")
                errors += 1

        cursor.close()
        result = {'classified': classified, 'errors': errors, 'total': len(observations)}
        logger.info(f"Batch terminé : {result}")
        return result


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BATCH_LIMIT

    pipeline = ImageClassificationPipeline(
        pg_host=os.getenv('POSTGRES_HOST', 'localhost'),
        pg_port=int(os.getenv('POSTGRES_PORT', '5432')),
        pg_user=os.getenv('POSTGRES_USER', 'insect_user'),
        pg_password=os.getenv('POSTGRES_PASSWORD', 'insect_pass'),
        pg_db=os.getenv('POSTGRES_DB', 'insect_lake')
    )

    try:
        result = pipeline.run(limit)
        print(f"✓ {result['classified']}/{result['total']} images classifiées ({result['errors']} erreurs)")
    finally:
        pipeline.close()


if __name__ == '__main__':
    main()