"""
Connexion a Chroma Cloud + logique "a la demande" :
quand l'utilisateur demande un actif, on va chercher des donnees fraiches
sur Twelve Data et on remplace UNIQUEMENT les documents de cet actif
dans la collection (pas besoin de tout recharger).
"""
import chromadb
from config import CHROMA_API_KEY, CHROMA_TENANT, CHROMA_DATABASE, COLLECTION_NAME
from market_data import fetch_time_series, build_documents
from timing import etape

_collection = None  # cache : on garde la connexion ouverte entre les appels


def get_collection():
    global _collection
    if _collection is None:
        with etape("Chroma - connexion initiale (1re fois seulement)"):
            client = chromadb.CloudClient(
                tenant=CHROMA_TENANT,
                database=CHROMA_DATABASE,
                api_key=CHROMA_API_KEY,
            )
            _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def refresh_symbol(symbol: str, label: str, outputsize: int = None):
    """
    Va chercher des donnees fraiches pour CE symbole uniquement,
    supprime les anciens documents de ce symbole dans Chroma,
    et ajoute les nouveaux. Les autres symboles ne sont pas touches.
    outputsize : nombre d'heures a analyser (adapte a la periode demandee par l'utilisateur).
    """
    collection = get_collection()

    with etape("Twelve Data - recuperation des prix"):
        data = fetch_time_series(symbol, outputsize=outputsize)

    with etape("Formatage des documents (local, CPU)"):
        documents, metadatas, ids = build_documents(symbol, label, data)

    with etape("Chroma - suppression anciens documents"):
        try:
            collection.delete(where={"symbol": symbol})
        except Exception:
            pass  # rien a supprimer la premiere fois

    with etape("Chroma - ajout nouveaux documents (+ embeddings)"):
        collection.add(documents=documents, metadatas=metadatas, ids=ids)

    return documents[0]  # le resume, utile pour affichage immediat


def get_summary(symbol: str):
    collection = get_collection()
    with etape("Chroma - recuperation du resume"):
        results = collection.get(where={"$and": [{"symbol": symbol}, {"type": "summary"}]})
    return results["documents"][0] if results["documents"] else None


def get_last_candles(symbol: str, n: int = 2):
    collection = get_collection()
    with etape("Chroma - recuperation des bougies"):
        results = collection.get(where={"$and": [{"symbol": symbol}, {"type": "candle"}]})
    paires = sorted(zip(results["documents"], results["metadatas"]),
                     key=lambda x: x[1]["datetime"], reverse=True)
    return [d for d, m in paires[:n]]