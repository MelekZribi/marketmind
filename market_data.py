"""
Logique de recuperation des donnees Twelve Data + transformation en documents.
Reutilisee a la fois par le mode "batch" (fetch_data.py) et le mode
"a la demande" (app.py, quand l'utilisateur pose une question).
"""
import requests
from config import TWELVE_DATA_API_KEY, TWELVE_DATA_BASE_URL, INTERVAL, OUTPUTSIZE, TIMEZONE


def fetch_time_series(symbol: str, outputsize: int = None) -> dict:
    """Appelle l'API Twelve Data et renvoie le JSON pour un symbole.
    outputsize (nombre d'heures a recuperer) : utilise la valeur par defaut de
    config.py si non precisee, sinon la valeur demandee (bornee a 1000, max Twelve Data)."""
    url = f"{TWELVE_DATA_BASE_URL}/time_series"
    taille = outputsize if outputsize else OUTPUTSIZE
    taille = min(taille, 1000)
    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "outputsize": taille,
        "timezone": TIMEZONE,
        "apikey": TWELVE_DATA_API_KEY,
    }
    response = requests.get(url, params=params, timeout=15)
    data = response.json()
    if data.get("status") == "error":
        raise RuntimeError(f"Erreur API Twelve Data pour {symbol} : {data.get('message')}")
    return data


def analyse_technique(values: list) -> dict:
    """
    Calcule une analyse technique en combinant DEUX strategies de trading
    populaires, pour donner une conclusion plus robuste qu'une seule regle :

    1) Support/Resistance : acheter pres du plancher, vendre pres du plafond.
    2) Croisement de moyennes mobiles (moving average crossover) : si le prix
       moyen recent (moyenne courte) est au-dessus du prix moyen sur une
       periode plus longue (moyenne longue), la dynamique est haussiere
       (et inversement) - c'est l'une des strategies les plus utilisees en
       analyse technique pour detecter un changement de tendance.

    values : liste de bougies Twelve Data, values[0] = la plus recente.
    Renvoie un dict avec tous les chiffres + un texte de raisonnement pret
    a etre donne au LLM ou affiche.
    """
    highs = [float(v["high"]) for v in values]
    lows = [float(v["low"]) for v in values]
    closes_recent_first = [float(v["close"]) for v in values]  # plus recent en premier
    closes_chrono = list(reversed(closes_recent_first))  # ordre chronologique (ancien -> recent)

    latest_close = closes_recent_first[0]
    resistance = max(highs)
    support = min(lows)
    range_size = resistance - support
    position_pct = (latest_close - support) / range_size * 100 if range_size > 0 else 50

    if position_pct <= 25:
        signal_support_resistance = "achat"
        raison_1 = f"le prix ({latest_close:.2f}) est proche du support ({support:.2f}), a {position_pct:.0f}% du bas de la fourchette"
    elif position_pct >= 75:
        signal_support_resistance = "vente"
        raison_1 = f"le prix ({latest_close:.2f}) est proche de la resistance ({resistance:.2f}), a {position_pct:.0f}% du haut de la fourchette"
    else:
        signal_support_resistance = "neutre"
        raison_1 = f"le prix ({latest_close:.2f}) est en zone neutre ({position_pct:.0f}% de la fourchette), ni pres du support ni de la resistance"

    # --- Strategie 2 : croisement de moyennes mobiles ---
    # Moyenne courte = les ~20% les plus recents de la periode, moyenne longue = tout.
    # (proportionnel a la periode demandee, plutot que des valeurs fixes 20/50 qui
    # n'auraient pas de sens sur une petite fenetre de donnees)
    n = len(closes_chrono)
    taille_courte = max(2, n // 5)
    sma_courte = sum(closes_chrono[-taille_courte:]) / taille_courte
    sma_longue = sum(closes_chrono) / n

    if sma_courte > sma_longue * 1.001:
        signal_moyennes = "achat"
        raison_2 = f"la moyenne recente ({sma_courte:.2f}) est au-dessus de la moyenne sur toute la periode ({sma_longue:.2f}) : dynamique haussiere"
    elif sma_courte < sma_longue * 0.999:
        signal_moyennes = "vente"
        raison_2 = f"la moyenne recente ({sma_courte:.2f}) est en-dessous de la moyenne sur toute la periode ({sma_longue:.2f}) : dynamique baissiere"
    else:
        signal_moyennes = "neutre"
        raison_2 = f"la moyenne recente ({sma_courte:.2f}) est proche de la moyenne longue ({sma_longue:.2f}) : pas de dynamique claire"

    # --- Conclusion combinee ---
    signaux = [signal_support_resistance, signal_moyennes]
    if signaux.count("achat") == 2:
        conclusion = "ACHAT (les 2 strategies sont d'accord : signal fort)"
    elif signaux.count("vente") == 2:
        conclusion = "VENTE (les 2 strategies sont d'accord : signal fort)"
    elif "achat" in signaux and "vente" in signaux:
        conclusion = "SIGNAL MITIGE (les 2 strategies se contredisent : prudence recommandee)"
    else:
        conclusion = "NEUTRE (aucune strategie ne donne de signal clair)"

    raisonnement = (
        f"Strategie 1 (Support/Resistance) : {raison_1} -> signal {signal_support_resistance}.\n"
        f"Strategie 2 (Croisement de moyennes mobiles) : {raison_2} -> signal {signal_moyennes}.\n"
        f"Conclusion combinee : {conclusion}."
    )

    return {
        "support": support, "resistance": resistance, "position_pct": position_pct,
        "sma_courte": sma_courte, "sma_longue": sma_longue,
        "signal_support_resistance": signal_support_resistance,
        "signal_moyennes": signal_moyennes,
        "conclusion": conclusion,
        "raisonnement": raisonnement,
    }


def build_documents(symbol: str, label: str, data: dict):
    """
    Transforme les donnees brutes en documents texte + metadonnees pour ChromaDB.
    Retourne (documents, metadatas, ids).
    """
    values = data["values"]
    documents, metadatas, ids = [], [], []

    latest = values[0]
    latest_close = float(latest["close"])
    analyse = analyse_technique(values)

    # Tendance : comparaison entre le debut et la fin de la periode analysee.
    # values[0] = la plus recente, values[-1] = la plus ancienne recuperee.
    prix_debut_periode = float(values[-1]["close"])
    variation_pct = (latest_close - prix_debut_periode) / prix_debut_periode * 100 if prix_debut_periode else 0
    if variation_pct > 0.5:
        tendance = f"en hausse (+{variation_pct:.2f}%)"
    elif variation_pct < -0.5:
        tendance = f"en baisse ({variation_pct:.2f}%)"
    else:
        tendance = f"stable ({variation_pct:+.2f}%)"

    duree_heures = len(values)  # le vrai nombre de bougies recuperees pour CETTE requete
    summary_text = (
        f"{label} ({symbol}) : prix actuel {latest_close}. "
        f"Tendance sur la periode : {tendance} (prix il y a {duree_heures}h : {prix_debut_periode}). "
        f"Calcule sur les {duree_heures} dernieres heures. "
        f"Derniere mise a jour: {latest['datetime']}.\n"
        f"{analyse['raisonnement']}"
    )
    documents.append(summary_text)
    metadatas.append({
        "symbol": symbol, "label": label, "type": "summary",
        "close": latest_close, "support": analyse["support"], "resistance": analyse["resistance"],
        "datetime": latest["datetime"],
    })
    ids.append(f"{symbol}-summary")

    # On ne stocke QUE les quelques dernieres bougies dans Chroma, pas les 100 :
    # le calcul support/resistance ci-dessus a deja utilise les 100 heures,
    # et get_last_candles() ne lit jamais plus que quelques bougies triees par date.
    # Stocker les 100 forcait Chroma a calculer 100 embeddings inutiles a chaque question.
    NB_BOUGIES_STOCKEES = 5
    for i, v in enumerate(values[:NB_BOUGIES_STOCKEES]):
        text = (
            f"{label} ({symbol}) le {v['datetime']} : "
            f"ouverture {v['open']}, plus haut {v['high']}, "
            f"plus bas {v['low']}, cloture {v['close']}."
        )
        documents.append(text)
        metadatas.append({"symbol": symbol, "label": label, "type": "candle", "datetime": v["datetime"]})
        ids.append(f"{symbol}-candle-{i}")

    return documents, metadatas, ids