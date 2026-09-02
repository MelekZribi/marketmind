"""
Petit utilitaire pour chronometrer chaque etape et afficher un
recapitulatif clair dans le terminal, avec l'etape la plus lente en evidence.
"""
import time
from contextlib import contextmanager

# Stocke les durees de la requete en cours (remis a zero a chaque nouvelle question)
_mesures = []


def reset():
    _mesures.clear()


@contextmanager
def etape(nom: str):
    debut = time.perf_counter()
    try:
        yield
    finally:
        duree_ms = (time.perf_counter() - debut) * 1000
        _mesures.append((nom, duree_ms))
        print(f"  [TEMPS] {nom:<35} {duree_ms:>8.1f} ms")


def afficher_recap():
    if not _mesures:
        return
    total = sum(d for _, d in _mesures)
    plus_lente = max(_mesures, key=lambda x: x[1])
    print("  " + "-" * 50)
    print(f"  [TEMPS] {'TOTAL':<35} {total:>8.1f} ms")
    print(f"  [TEMPS] Etape la plus lente : {plus_lente[0]} ({plus_lente[1]:.1f} ms, "
          f"{plus_lente[1] / total * 100:.0f}% du temps total)")
    print()
