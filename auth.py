"""
Routes d'authentification pour MarketMind : inscription, connexion, deconnexion.
"""
from flask import Blueprint, request, render_template, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Nom d'utilisateur et mot de passe requis.")
            return render_template("register.html")

        if User.query.filter_by(username=username).first():
            flash("Ce nom d'utilisateur est deja pris.")
            return render_template("register.html")

        if len(password) < 6:
            flash("Le mot de passe doit faire au moins 6 caracteres.")
            return render_template("register.html")

        # Le mot de passe n'est JAMAIS stocke en clair, seulement son hash
        nouvel_utilisateur = User(
            username=username,
            password_hash=generate_password_hash(password),
        )
        db.session.add(nouvel_utilisateur)
        db.session.commit()

        login_user(nouvel_utilisateur)
        return redirect(url_for("index"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        utilisateur = User.query.filter_by(username=username).first()
        if utilisateur and check_password_hash(utilisateur.password_hash, password):
            login_user(utilisateur)
            return redirect(url_for("index"))

        flash("Nom d'utilisateur ou mot de passe incorrect.")
        return render_template("login.html")

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
