"""
Envoi d'emails transactionnels (reset de mot de passe) via l'API Resend.

Necessite la variable d'environnement RESEND_API_KEY (creation de compte
gratuite sur resend.com, cle generee dans Dashboard > API Keys).

Limite importante a connaitre : tant qu'aucun domaine d'envoi n'est
verifie sur le compte Resend, l'adresse d'expedition par defaut
"onboarding@resend.dev" ne peut envoyer qu'a l'adresse email du
compte Resend lui-meme (limite anti-spam de Resend). Pour envoyer a
n'importe quel utilisateur inscrit sur AICostBill, il faudra verifier
un domaine (ex: aicostbill.com ou un sous-domaine) dans Resend et
mettre a jour EMAIL_FROM en consequence.
"""
import os
import requests

RESEND_API_URL = "https://api.resend.com/emails"
EMAIL_FROM = os.environ.get("EMAIL_FROM", "AICostBill <onboarding@resend.dev>")


class EmailError(Exception):
    pass


def send_email(to, subject, html_body):
    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise EmailError("RESEND_API_KEY non configuree.")

    resp = requests.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "from": EMAIL_FROM,
            "to": [to],
            "subject": subject,
            "html": html_body,
        },
        timeout=15,
    )
    if not resp.ok:
        raise EmailError(f"Resend a refuse l'envoi ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


def send_password_reset_email(to, reset_url):
    html = f"""
    <div style="font-family: sans-serif; max-width: 480px; margin: 0 auto;">
      <h2 style="color:#111827;">Reinitialise ton mot de passe</h2>
      <p style="color:#374151;">
        Tu as demande a reinitialiser ton mot de passe AICostBill. Clique sur le
        bouton ci-dessous (valable 1 heure) :
      </p>
      <p style="text-align:center; margin: 24px 0;">
        <a href="{reset_url}"
           style="background:#4f46e5; color:#fff; padding:12px 24px; border-radius:8px;
                  text-decoration:none; font-weight:600;">
          Choisir un nouveau mot de passe
        </a>
      </p>
      <p style="color:#9ca3af; font-size:13px;">
        Si tu n'es pas a l'origine de cette demande, ignore simplement cet email.
      </p>
    </div>
    """
    return send_email(to, "Reinitialisation de ton mot de passe AICostBill", html)
