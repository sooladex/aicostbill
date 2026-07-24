"""
Chiffrement des cles API des utilisateurs (OpenAI / Anthropic) avant stockage
en base. On ne stocke jamais une cle en clair : uniquement sa version
chiffree (Fernet, AES symmetrique). La cle de chiffrement elle-meme vit dans
la variable d'environnement CREDENTIALS_SECRET_KEY (a definir sur Railway),
jamais dans le code ni dans la base.
"""
import os
from cryptography.fernet import Fernet, InvalidToken

# Cle de secours pour le dev local uniquement. En production, la variable
# d'environnement CREDENTIALS_SECRET_KEY DOIT etre definie avec une vraie
# cle generee (Fernet.generate_key()), sinon toutes les cles API des
# utilisateurs seraient chiffrees avec une cle publique connue.
_DEV_FALLBACK_KEY = "Zt3q9mP6yV1sJd8oQe0hT4bU7xW2nC5aFk9rIlOu3Yc="


def _fernet():
    key = os.environ.get("CREDENTIALS_SECRET_KEY", _DEV_FALLBACK_KEY)
    return Fernet(key.encode())


def encrypt(plain_text):
    return _fernet().encrypt(plain_text.encode()).decode()


def decrypt(token):
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def mask(plain_text, visible=4):
    """Pour l'affichage : ne montre jamais la cle en entier."""
    if not plain_text or len(plain_text) <= visible:
        return "*" * 8
    return "*" * 8 + plain_text[-visible:]
