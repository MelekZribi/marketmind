"""
Appel au LLM heberge sur Groq.
Le LLM ne connait pas les prix : on lui donne le contexte (recupere dans ChromaDB)
et il redige une reponse claire en francais a partir de ce contexte.
"""
import json
import requests
from config import GROQ_API_KEY, GROQ_MODEL
from timing import etape

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def extract_symbol(question: str, historique: list = None):
    """
    Demande a Groq de deviner le(s) symbole(s) Twelve Data + la periode demandee
    (en jours) a partir de la question libre de l'utilisateur, EN TENANT COMPTE
    de l'historique de conversation (pour resoudre "oui"/"non"/"et l'autre ?").
    Gere aussi bien 1 seul actif ("prix de l'or") que plusieurs ("compare l'or et l'argent").
    Renvoie (assets, jours) ou assets est une LISTE de {"symbol":..., "label":...}
    (liste vide si aucun actif detecte). jours=None si aucune periode mentionnee.
    """
    if not GROQ_API_KEY:
        print("[extract_symbol] GROQ_API_KEY est vide - verifie que $env:GROQ_API_KEY est bien defini dans CETTE fenetre PowerShell.")
        return [], None, False

    system_prompt = (
        # --- Role prompting : definir clairement le role et les limites ---
        "Tu es un module d'extraction, pas un assistant conversationnel. "
        "Ta tache : detecter quel(s) actif(s) financier(s) une question mentionne "
        "(0, 1, ou plusieurs si comparaison), la periode demandee, ET si "
        "l'utilisateur veut un GRAPHIQUE visuel plutot qu'une reponse textuelle. "
        "Tu ne dois JAMAIS repondre a la question elle-meme.\n\n"
        # --- Utilisation de l'historique pour resoudre les references ---
        "Un historique de conversation peut etre fourni avant la question. "
        "Utilise-le pour comprendre les references implicites : si le message "
        "precedent du bot proposait une analyse d'un actif et que l'utilisateur "
        "repond 'oui', 'ok', 'vas-y', etc., renvoie l'actif dont il etait "
        "question dans ce message precedent.\n\n"
        # --- Contrainte de format stricte ---
        "Reponds UNIQUEMENT avec un objet JSON, sans aucun texte autour.\n"
        "Format : {\"assets\": [{\"symbol\": \"...\", \"label\": \"...\"}, ...], "
        "\"jours\": N, \"graphique\": true/false}\n"
        "Si aucun actif n'est mentionne : {\"assets\": [], \"jours\": null, \"graphique\": false}\n\n"
        # --- Contrainte de refus explicite (regle anti-hallucination) ---
        "Mets assets=[] si la question est une salutation, un remerciement, "
        "des menus propos, une question generale sans actif precis (et sans "
        "actif deductible de l'historique), OU si l'actif mentionne n'est "
        "manifestement pas un instrument financier reel. "
        "N'INVENTE JAMAIS un symbole pour faire plaisir : si tu doutes, ne l'ajoute pas.\n\n"
        "'jours' = la periode d'analyse demandee (partagee pour tous les actifs), "
        "convertie en nombre de jours. Si aucune periode n'est mentionnee, mets jours a null.\n\n"
        "'graphique' = true UNIQUEMENT si l'utilisateur demande explicitement de "
        "VOIR quelque chose de visuel (trace, dessine, montre le graphique, la "
        "courbe, un chart, une visualisation...). Une simple question sur le "
        "prix, la tendance ou un signal achat/vente en TEXTE reste graphique=false, "
        "meme si elle mentionne 'l'evolution' ou 'la tendance' sans demander "
        "explicitement de le VOIR visuellement.\n\n"
        "Conventions Twelve Data :\n"
        "- metaux precieux : XAU/USD (or), XAG/USD (argent), XPT/USD (platine), XPD/USD (palladium)\n"
        "- energie : WTI/USD (petrole), NATGAS/USD (gaz naturel)\n"
        "- devises : EUR/USD, GBP/USD, USD/JPY, etc.\n"
        "- crypto : BTC/USD, ETH/USD, etc.\n"
        "- actions : le ticker boursier standard, ex: AAPL, TSLA, MSFT\n\n"
        # --- Few-shot examples : cas normaux, graphique, refus, et reference contextuelle ---
        "Exemples (sans historique) :\n"
        "'dois-je acheter le petrole ?' -> "
        "{\"assets\": [{\"symbol\": \"WTI/USD\", \"label\": \"Petrole\"}], \"jours\": null, \"graphique\": false}\n"
        "'tendance de l or sur les 4 derniers jours' -> "
        "{\"assets\": [{\"symbol\": \"XAU/USD\", \"label\": \"Or\"}], \"jours\": 4, \"graphique\": false}\n"
        "'trace-moi la courbe de l or sur les 4 derniers jours' -> "
        "{\"assets\": [{\"symbol\": \"XAU/USD\", \"label\": \"Or\"}], \"jours\": 4, \"graphique\": true}\n"
        "'montre-moi le graphique du bitcoin' -> "
        "{\"assets\": [{\"symbol\": \"BTC/USD\", \"label\": \"Bitcoin\"}], \"jours\": null, \"graphique\": true}\n"
        "'compare l or et l argent' -> "
        "{\"assets\": [{\"symbol\": \"XAU/USD\", \"label\": \"Or\"}, {\"symbol\": \"XAG/USD\", \"label\": \"Argent\"}], \"jours\": null, \"graphique\": false}\n"
        "'bonjour' -> {\"assets\": [], \"jours\": null, \"graphique\": false}\n"
        "'prix du zorkoin' -> {\"assets\": [], \"jours\": null, \"graphique\": false}\n"
        "Exemple AVEC historique (le bot vient de parler du Bitcoin, l'utilisateur confirme) :\n"
        "historique: [...assistant: 'Veux-tu que je regarde le Bitcoin ?'], question: 'oui' -> "
        "{\"assets\": [{\"symbol\": \"BTC/USD\", \"label\": \"Bitcoin\"}], \"jours\": null, \"graphique\": false}"
    )

    messages = [{"role": "system", "content": system_prompt}]
    for m in (historique or [])[-6:]:  # on limite l'historique envoye pour rester rapide/economique
        messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
    messages.append({"role": "user", "content": question})

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

    try:
        with etape("Groq - extraction du/des symbole(s) (appel LLM #1)"):
            response = requests.post(GROQ_URL, headers=headers, json=payload, timeout=20)
        data = response.json()

        if "error" in data:
            print(f"[extract_symbol] Erreur renvoyee par Groq : {data['error']}")
            return [], None, False

        content = data["choices"][0]["message"]["content"].strip()
        # Certains modeles entourent le JSON de balises ```json ... ``` malgre la consigne -> on les retire
        if content.startswith("```"):
            content = content.strip("`")
            content = content.replace("json\n", "", 1).strip()

        parsed = json.loads(content)
        return parsed.get("assets", []), parsed.get("jours"), parsed.get("graphique", False)
    except Exception as e:
        print(f"[extract_symbol] Exception : {type(e).__name__}: {e}")
        return [], None, False


def ask_groq(question: str, context: str, historique: list = None) -> str:
    if not GROQ_API_KEY:
        return "Cle GROQ_API_KEY manquante. Definis-la avant de lancer l'app."

    system_prompt = (
        # --- Role prompting ---
        "Tu es un assistant d'analyse trading factuelle. Ton role est d'expliquer "
        "des donnees de marche passees, jamais de predire l'avenir.\n\n"
        # --- Contraintes de comportement, explicites et numerotees ---
        "Regles strictes :\n"
        "1. Base-toi UNIQUEMENT sur les donnees dans la balise <contexte> ci-dessous. "
        "N'invente aucun chiffre, aucune date, aucun evenement.\n"
        "2. Si le contexte ne suffit pas pour repondre, dis-le clairement plutot "
        "que de deviner.\n"
        "3. Tu ne predis JAMAIS un prix futur. Si on te demande une prediction, "
        "explique que tu analyses seulement les donnees passees, pas l'avenir.\n"
        "4. Reponds en francais, de facon claire et concise (3-4 phrases maximum).\n"
        "5. Le signal achat/vente du contexte est indicatif (base sur support/"
        "resistance), pas un conseil financier garanti — tu peux le rappeler si utile.\n"
        "6. Tu peux t'appuyer sur l'historique de conversation fourni pour garder "
        "la coherence (ex: l'utilisateur dit 'oui' a une proposition precedente), "
        "mais les CHIFFRES doivent toujours venir du contexte actuel, pas de "
        "chiffres mentionnes plus tot dans l'historique (ils peuvent etre perimes).\n"
        "7. Termine ta reponse par UNE question de suivi courte et pertinente "
        "quand cela apporte une vraie valeur (ex: proposer d'analyser un actif "
        "lie, une autre periode, ou une comparaison). N'en pose PAS si la "
        "question ne s'y prete pas naturellement (evite de forcer une question "
        "a chaque reponse).\n"
        "Exemples de bonnes questions de suivi :\n"
        "- Apres une analyse de l'or : 'Veux-tu que je compare avec l'argent ?'\n"
        "- Apres une analyse sur 1 jour : 'Souhaites-tu voir la tendance sur une semaine ?'\n"
        "- Apres un signal neutre : 'Je peux verifier un autre actif si tu veux.'\n\n"
        f"<contexte>\n{context}\n</contexte>"
    )

    messages = [{"role": "system", "content": system_prompt}]
    for m in (historique or [])[-6:]:
        messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
    messages.append({"role": "user", "content": question})

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.3,
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

    with etape("Groq - redaction de la reponse finale (appel LLM #2)"):
        response = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)
        data = response.json()

    if "error" in data:
        return f"Erreur Groq : {data['error'].get('message', data['error'])}"

    return data["choices"][0]["message"]["content"]


def answer_general(question: str, historique: list = None) -> str:
    """
    Gere les questions SANS actif financier detecte (salutations, remerciements,
    questions hors-sujet) - entierement via le LLM, sans aucune regle codee en dur.
    Le prompt (role prompting + contraintes) suffit a cadrer le comportement.
    """
    if not GROQ_API_KEY:
        return "Cle GROQ_API_KEY manquante. Definis-la avant de lancer l'app."

    system_prompt = (
        # --- Role prompting ---
        "Tu es l'assistant conversationnel d'un chatbot d'analyse trading "
        "(or, matieres premieres, devises, crypto, actions).\n\n"
        # --- Contraintes de comportement ---
        "Regles :\n"
        "1. Si la question est une salutation, un remerciement ou une formule "
        "de politesse : reponds chaleureusement en 1 phrase, puis rappelle "
        "brievement que tu peux analyser un actif financier (prix, tendance, "
        "signal achat/vente).\n"
        "2. Si la question est totalement hors-sujet (rien a voir avec la "
        "finance) : reponds poliment que ce n'est pas ton domaine, et propose "
        "de revenir a une question financiere.\n"
        "3. Si la question mentionne un actif qui n'existe manifestement pas "
        "(invente, absurde) : dis-le clairement, sans inventer de donnees.\n"
        "4. Utilise l'historique de conversation fourni si utile pour rester "
        "coherent avec ce qui vient d'etre dit.\n"
        "5. Reste toujours bref (1-2 phrases), en francais, ton amical mais "
        "professionnel.\n"
        "6. Ne donne JAMAIS de chiffre ou de prix ici : tu n'as recu aucune "
        "donnee de marche pour cette question."
    )

    messages = [{"role": "system", "content": system_prompt}]
    for m in (historique or [])[-6:]:
        messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})
    messages.append({"role": "user", "content": question})

    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": 0.5,
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}

    with etape("Groq - reponse conversationnelle (appel LLM #2 bis)"):
        response = requests.post(GROQ_URL, headers=headers, json=payload, timeout=20)
        data = response.json()

    if "error" in data:
        return f"Erreur Groq : {data['error'].get('message', data['error'])}"

    return data["choices"][0]["message"]["content"] 