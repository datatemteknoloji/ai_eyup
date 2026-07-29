"""
RAG reranking servisi — HuggingFace cross-encoder ile embedding aramasından
gelen adayları sorguya göre yeniden sıralar.

Neden gerekli: Chroma'daki cosine-benzerlik araması ("bi-encoder") hızlıdır ama
kaba bir sıralama verir. Cross-encoder ("reranker") sorgu+doküman çiftini
BİRLİKTE modele verip gerçek bir alaka skoru üretir — çok daha isabetli ama
daha yavaştır. Bu yüzden önce embedding ile geniş bir aday kümesi (ör. 15-20)
çekilir, sonra bu küçük küme reranker ile yeniden sıralanıp en iyi top_k alınır.

Model process ömrü boyunca bir kez yüklenir (lazy, thread-safe). Bu container'da
GPU yok — CPU'da çalışır; bu yüzden aday sayısı küçük tutulmalı (bkz.
runtime_settings: rag_reranker_candidates). Model indirilemez/yüklenemezse
(offline, disk vb.) reranking sessizce devre dışı kalır ve RAG akışı ESKİ
(yalnızca embedding sıralı) davranışına döner — hiçbir şeyi bozmaz.
"""
from __future__ import annotations

import logging
import threading
from typing import List

logger = logging.getLogger(__name__)

_model = None
_model_name: str = ""
_load_failed = False
_lock = threading.Lock()


def _load_model(model_name: str):
    global _model, _model_name, _load_failed
    with _lock:
        if _model is not None and _model_name == model_name:
            return _model
        if _load_failed and _model_name == model_name:
            return None
        try:
            from sentence_transformers import CrossEncoder
            logger.info("[Reranker] model yükleniyor: %s (ilk çağrıda birkaç saniye sürebilir)", model_name)
            _model = CrossEncoder(model_name, max_length=512)
            _model_name = model_name
            _load_failed = False
            logger.info("[Reranker] model hazır: %s", model_name)
        except Exception as e:
            logger.warning("[Reranker] model yüklenemedi, reranking devre dışı: %s", e)
            _model = None
            _model_name = model_name
            _load_failed = True
    return _model


def is_enabled() -> bool:
    try:
        from app.services import runtime_settings
        return bool(runtime_settings.get_bool("rag_reranker_enabled"))
    except Exception:
        return False


def rerank(query: str, documents: List[str], top_k: int) -> List[int]:
    """
    `documents` listesini `query`'e göre yeniden sıralar; en alakalı `top_k`
    öğenin ORİJİNAL indekslerini (documents listesindeki), azalan alaka
    skoruna göre sıralı şekilde döndürür.

    Reranker kapalıysa / model yüklenemezse / hata olursa, orijinal sırayı
    (embedding sıralamasını) koruyarak ilk `top_k` indeksi döndürür — hiçbir
    zaman RAG akışını kesmez.
    """
    n = len(documents)
    if n == 0 or top_k <= 0:
        return []
    fallback = list(range(min(top_k, n)))
    if not query or not query.strip():
        return fallback
    if not is_enabled():
        return fallback

    try:
        from app.services import runtime_settings
        model_name = runtime_settings.get_str("rag_reranker_model") or "BAAI/bge-reranker-v2-m3"
    except Exception:
        model_name = "BAAI/bge-reranker-v2-m3"

    model = _load_model(model_name)
    if model is None:
        return fallback

    try:
        pairs = [[query, doc or ""] for doc in documents]
        scores = model.predict(pairs)
        order = sorted(range(n), key=lambda i: float(scores[i]), reverse=True)
        return order[:top_k]
    except Exception as e:
        logger.warning("[Reranker] tahmin başarısız, orijinal sıralamaya dönülüyor: %s", e)
        return fallback
