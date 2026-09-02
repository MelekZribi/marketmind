"""
Configuration du projet.
Toutes les cles/secrets viennent de variables d'environnement, jamais du code.
"""
import os

# --- Twelve Data (donnees de marche) ---
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "demo")
TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"

# --- Chroma Cloud (base de donnees vectorielle) ---
CHROMA_API_KEY = os.environ.get("CHROMA_API_KEY", "")
CHROMA_TENANT = os.environ.get("CHROMA_TENANT", "")
CHROMA_DATABASE = os.environ.get("CHROMA_DATABASE", "trading_db")
COLLECTION_NAME = "trading_data"

# --- Groq (le LLM qui redige les reponses) ---
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "openai/gpt-oss-20b"   # modele rapide et peu couteux sur Groq

# --- Alternatives gratuites pour les actifs payants sur le plan Twelve Data gratuit ---
# Format : symbole demande -> (symbole alternatif gratuit, explication)
# Le plan gratuit couvre : actions/ETF US, forex, crypto.
# Les matieres premieres (argent, platine, petrole...) necessitent un plan payant (Grow+),
# donc on propose un ETF equivalent qui, lui, se negocie comme une action normale.
PAID_ASSET_ALTERNATIVES = {
    "XAG/USD": ("SLV", "l'ETF iShares Silver Trust (SLV), qui suit de tres pres le prix de l'argent physique"),
    "XPT/USD": ("PPLT", "l'ETF abrdn Physical Platinum Shares (PPLT), qui suit le prix du platine"),
    "XPD/USD": ("PALL", "l'ETF abrdn Physical Palladium Shares (PALL), qui suit le prix du palladium"),
    "WTI/USD": ("USO", "l'ETF United States Oil Fund (USO), qui suit le prix du petrole"),
    "NATGAS/USD": ("UNG", "l'ETF United States Natural Gas Fund (UNG), qui suit le prix du gaz naturel"),
}

INTERVAL = "1h"
OUTPUTSIZE = 100
TIMEZONE = "Africa/Tunis"

# --- Comptes utilisateurs (authentification) ---
# SECRET_KEY signe les sessions de connexion (cookies) : change-la en prod !
# En dev, une valeur par defaut suffit pour ne pas bloquer, mais definis-la
# via variable d'environnement avant toute mise en ligne publique.
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-a-changer-en-production")
DATABASE_PATH = os.environ.get("DATABASE_PATH", "marketmind.db")
