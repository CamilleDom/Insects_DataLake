"""
Classification d'images d'insectes via CNN pré-entraîné (transfer learning).

Utilise MobileNetV2 (torchvision, poids ImageNet-1k) pour obtenir une
prédiction indicative de la classe visuelle d'une observation photographiée.

Choix assumé : pas de modèle "espèces d'insectes" spécifique (aucun dataset
annoté disponible dans le cadre du projet). On utilise à la place les classes
ImageNet directement liées aux insectes (~17 classes : papillons, libellules,
criquets, mantes, coléoptères...) pour obtenir un signal exploitable sans
sur-promettre une précision taxonomique que le modèle ne peut pas garantir.
"""

import io
import logging
from typing import Optional, Dict

import requests
import torch
from PIL import Image
from torchvision.models import mobilenet_v2, MobileNet_V2_Weights

logger = logging.getLogger(__name__)

# Chargement paresseux (lazy) : le modèle n'est chargé qu'au premier appel,
# et réutilisé ensuite (évite de recharger les poids à chaque image).
_model = None
_transform = None
_categories = None
_insect_indices = None

# Mots-clés utilisés pour repérer dynamiquement les classes ImageNet liées
# aux insectes, à partir de la vraie liste des catégories du modèle chargé
# (plus robuste qu'un hardcoding d'indices numériques, qui pourrait varier
# selon la version des poids).
INSECT_KEYWORDS = [
    'ant', 'bee', 'beetle', 'butterfly', 'cicada', 'cockroach', 'cricket',
    'damselfly', 'dragonfly', 'fly', 'grasshopper', 'lacewing', 'leafhopper',
    'locust', 'mantis', 'mosquito', 'moth', 'wasp', 'weevil', 'stick',
    'monarch', 'admiral', 'ringlet', 'sulphur', 'lycaenid', 'cabbage butterfly',
]


def _load_model():
    """Charge MobileNetV2 et construit l'ensemble des classes 'insectes'."""
    global _model, _transform, _categories, _insect_indices

    if _model is not None:
        return

    logger.info("Chargement de MobileNetV2 (poids ImageNet-1k)...")
    weights = MobileNet_V2_Weights.IMAGENET1K_V2
    _model = mobilenet_v2(weights=weights)
    _model.eval()
    _transform = weights.transforms()
    _categories = weights.meta["categories"]

    _insect_indices = {
        i for i, name in enumerate(_categories)
        if any(kw in name.lower() for kw in INSECT_KEYWORDS)
    }
    logger.info(
        f"Modèle chargé : {len(_insect_indices)} classes 'insectes' "
        f"identifiées sur {len(_categories)} classes ImageNet."
    )


def download_image(url: str, timeout: int = 10) -> Optional[Image.Image]:
    """Télécharge et décode une image depuis une URL. Retourne None si échec."""
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        logger.warning(f"Échec du téléchargement/décodage de {url}: {e}")
        return None


def classify_image(image_url: str) -> Optional[Dict]:
    """
    Classifie une image et retourne :
    {
        'predicted_class': str,
        'confidence': float,          # probabilité softmax de la classe top-1
        'is_likely_insect': bool,     # True si une classe insecte est dans le top-5
        'top5': [(classe, proba), ...]
    }
    Retourne None si le téléchargement ou l'inférence échoue.
    """
    _load_model()

    img = download_image(image_url)
    if img is None:
        return None

    try:
        input_tensor = _transform(img).unsqueeze(0)

        with torch.no_grad():
            output = _model(input_tensor)
            probabilities = torch.nn.functional.softmax(output[0], dim=0)

        top5_prob, top5_idx = torch.topk(probabilities, 5)

        top5 = [
            (_categories[idx.item()], round(prob.item(), 4))
            for prob, idx in zip(top5_prob, top5_idx)
        ]

        best_idx = top5_idx[0].item()
        is_likely_insect = any(idx.item() in _insect_indices for idx in top5_idx)

        return {
            'predicted_class': _categories[best_idx],
            'confidence': round(top5_prob[0].item(), 4),
            'is_likely_insect': is_likely_insect,
            'top5': top5
        }
    except Exception as e:
        logger.error(f"Échec de la classification pour {image_url}: {e}")
        return None