"""
Interface web MarketMind (ex-Chatbot Trading) - avec comptes utilisateurs.
Flux : question libre -> Groq devine le symbole -> Twelve Data recupere les
donnees -> si l'actif est payant, on essaie une alternative gratuite connue ->
Chroma est mis a jour pour CE symbole -> Groq redige la reponse finale.
Chaque question posee est sauvegardee dans l'historique personnel de l'utilisateur.
"""
import os
from datetime import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_login import LoginManager, login_required, current_user

from config import PAID_ASSET_ALTERNATIVES, SECRET_KEY, DATABASE_PATH
from chroma_service import refresh_symbol, get_summary, get_last_candles
from llm_service import extract_symbol, ask_groq, answer_general
from market_data import fetch_time_series, analyse_technique
from models import db, User, Conversation, Message
from auth import auth_bp
import timing

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DATABASE_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
app.register_blueprint(auth_bp)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# Cree les tables si elles n'existent pas encore (1re fois seulement)
with app.app_context():
    db.create_all()


def est_erreur_plan_payant(erreur: Exception) -> bool:
    """Detecte si l'erreur Twelve Data vient d'une restriction de plan (pas d'un symbole invalide)."""
    msg = str(erreur).lower()
    mots_cles = ["plan", "upgrade", "subscription", "grow", "not available", "permission"]
    return any(mot in msg for mot in mots_cles)


@app.route("/")
@login_required
def index():
    return render_template("index.html", username=current_user.username)


def recuperer_contexte_pour_actif(symbol: str, label: str, outputsize: int):
    """
    Rafraichit et recupere le contexte (resume + bougies) pour UN actif.
    Gere aussi le fallback vers une alternative gratuite si l'actif est payant.
    Renvoie (contexte_texte, note_explicative) ou leve une exception si echec total.
    """
    note = ""
    try:
        refresh_symbol(symbol, label, outputsize=outputsize)
    except Exception as e:
        if est_erreur_plan_payant(e) and symbol in PAID_ASSET_ALTERNATIVES:
            alt_symbol, explication = PAID_ASSET_ALTERNATIVES[symbol]
            note = (
                f"(Note : {label} ({symbol}) necessite un plan Twelve Data payant. "
                f"Je te montre a la place {explication}.)\n\n"
            )
            symbol, label = alt_symbol, f"{label} (via {alt_symbol})"
            refresh_symbol(symbol, label, outputsize=outputsize)  # si ca echoue aussi, on laisse remonter l'exception
        elif est_erreur_plan_payant(e):
            raise RuntimeError(
                f"{label} ({symbol}) necessite un plan Twelve Data payant (Grow ou superieur), "
                f"et je n'ai pas d'alternative gratuite connue pour cet actif."
            )
        else:
            raise

    summary = get_summary(symbol) or ""
    candles = get_last_candles(symbol, n=2)
    contexte = summary + "\n" + "\n".join(candles)
    return contexte, note


def construire_donnees_graphique(symbol: str, label: str, outputsize: int):
    """
    Recupere les donnees brutes (sans passer par Chroma, on a besoin de TOUS
    les points pour un vrai graphique, pas juste le resume), calcule l'analyse
    technique (support/resistance + moyennes mobiles), et prepare tout pour
    Chart.js : la courbe de prix + les 2 barrieres horizontales.
    """
    data = fetch_time_series(symbol, outputsize=outputsize)
    values = data["values"]  # values[0] = le plus recent -> on inverse pour l'ordre chronologique
    analyse = analyse_technique(values)
    values_chrono = list(reversed(values))
    return {
        "label": f"{label} ({symbol})",
        "labels": [v["datetime"] for v in values_chrono],
        "values": [float(v["close"]) for v in values_chrono],
        "support": analyse["support"],
        "resistance": analyse["resistance"],
    }, analyse


def obtenir_ou_creer_conversation(conversation_id, premiere_question: str):
    """
    Si conversation_id est fourni et appartient bien a l'utilisateur connecte,
    on la reutilise. Sinon, on cree une nouvelle conversation (comme un nouveau
    "chat" dans ChatGPT/Claude), avec un titre base sur la 1re question posee.
    """
    if conversation_id:
        conv = Conversation.query.filter_by(id=conversation_id, user_id=current_user.id).first()
        if conv:
            return conv

    titre = premiere_question[:60] + ("..." if len(premiere_question) > 60 else "")
    conv = Conversation(user_id=current_user.id, title=titre)
    db.session.add(conv)
    db.session.commit()
    return conv


def sauvegarder_message(conversation: Conversation, role: str, content: str):
    """Ajoute un message (user ou assistant) a la conversation, et met a jour sa date."""
    msg = Message(conversation_id=conversation.id, role=role, content=content)
    db.session.add(msg)
    conversation.updated_at = datetime.utcnow()
    db.session.commit()


@app.route("/ask", methods=["POST"])
@login_required
def ask():
    timing.reset()
    question = request.json.get("question", "").strip()
    historique = request.json.get("history", [])  # [{role, content}, ...] envoye par le navigateur
    conversation_id = request.json.get("conversation_id")  # None si nouvelle discussion
    print(f"\n--- {current_user.username} : {question!r} (historique : {len(historique)} messages) ---")
    if not question:
        return jsonify({"answer": "Pose une question."})

    conversation = obtenir_ou_creer_conversation(conversation_id, question)
    sauvegarder_message(conversation, "user", question)

    assets, jours, graphique = extract_symbol(question, historique)
    if not assets:
        answer_text = answer_general(question, historique)
        sauvegarder_message(conversation, "assistant", answer_text)
        timing.afficher_recap()
        return jsonify({"answer": answer_text, "conversation_id": conversation.id})

    # jours -> nombre d'heures a recuperer (interval=1h). Sans periode precisee, on garde le defaut (config.py).
    outputsize = min(jours * 24, 1000) if jours else None
    if jours:
        print(f"  Periode demandee : {jours} jour(s) -> {outputsize} bougies horaires")
    print(f"  Actif(s) detecte(s) : {[a['label'] for a in assets]} | graphique demande : {graphique}")

    # --- Cas graphique : l'utilisateur veut VOIR une courbe, pas juste du texte ---
    if graphique:
        premier_actif = assets[0]  # un graphique = 1 actif a la fois, pour rester lisible
        try:
            chart_data, analyse = construire_donnees_graphique(
                premier_actif["symbol"], premier_actif["label"],
                outputsize or 100
            )
        except Exception as e:
            return jsonify({"answer": f"Impossible de recuperer les donnees du graphique : {e}"})

        periode_txt = f"les {jours} derniers jours" if jours else "la periode par defaut"
        contexte_analyse = (
            f"{premier_actif['label']} ({premier_actif['symbol']}) sur {periode_txt} "
            f"({len(chart_data['values'])} points).\n{analyse['raisonnement']}"
        )
        raisonnement_llm = ask_groq(question, contexte_analyse, historique)
        sauvegarder_message(conversation, "assistant", raisonnement_llm)
        timing.afficher_recap()
        return jsonify({"answer": raisonnement_llm, "chart": chart_data, "conversation_id": conversation.id})

    # --- Cas normal : question textuelle, reponse redigee par le LLM ---
    contextes = []
    notes = ""
    for actif in assets:
        try:
            contexte, note = recuperer_contexte_pour_actif(actif["symbol"], actif["label"], outputsize)
            contextes.append(f"--- {actif['label']} ---\n{contexte}")
            notes += note
        except Exception as e:
            contextes.append(f"--- {actif['label']} ---\n(donnees indisponibles : {e})")

    context_complet = "\n\n".join(contextes)
    answer_text = notes + ask_groq(question, context_complet, historique)
    sauvegarder_message(conversation, "assistant", answer_text)
    timing.afficher_recap()
    return jsonify({"answer": answer_text, "conversation_id": conversation.id})


@app.route("/conversations")
@login_required
def list_conversations():
    """Liste les discussions de l'utilisateur, la plus recente d'abord."""
    convs = Conversation.query.filter_by(user_id=current_user.id) \
        .order_by(Conversation.updated_at.desc()).all()
    return jsonify([
        {"id": c.id, "title": c.title, "date": c.updated_at.strftime("%d/%m/%Y %H:%M")}
        for c in convs
    ])


@app.route("/conversations/<int:conversation_id>/messages")
@login_required
def conversation_messages(conversation_id):
    """Renvoie tous les messages d'une discussion (pour la recharger dans le chat)."""
    conv = Conversation.query.filter_by(id=conversation_id, user_id=current_user.id).first()
    if not conv:
        return jsonify({"error": "Discussion introuvable"}), 404
    return jsonify([{"role": m.role, "content": m.content} for m in conv.messages])


@app.route("/conversations/<int:conversation_id>", methods=["DELETE"])
@login_required
def delete_conversation(conversation_id):
    conv = Conversation.query.filter_by(id=conversation_id, user_id=current_user.id).first()
    if not conv:
        return jsonify({"error": "Discussion introuvable"}), 404
    db.session.delete(conv)
    db.session.commit()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True, port=5000)