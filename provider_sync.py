"""
Recuperation automatique des couts reels via les API d'administration
d'OpenAI et Anthropic.

Principe :
- L'agence colle une cle "Admin API" (pas une cle API normale) dans
  Parametres > Connexions API. Cette cle donne acces en LECTURE SEULE aux
  couts/usage de TOUTE l'organisation OpenAI ou Anthropic de l'agence.
- OpenAI et Anthropic permettent de decouper les couts par "project" (OpenAI)
  ou "workspace" (Anthropic). Si l'agence cree un project/workspace distinct
  par client final (bonne pratique courante), on peut alors relier
  automatiquement chaque project_id/workspace_id a un client AICostBill
  (voir client_provider_links) et repartir les couts sans aucune saisie
  manuelle.
- Les couts non rattaches a un client connu sont ignores (on ne devine pas).

Limites connues (a documenter cote utilisateur) :
- Necessite une cle Admin API (differente d'une cle API standard), creee par
  le proprietaire/admin de l'organisation OpenAI ou Anthropic du client.
- Ne fonctionne que si l'agence isole deja ses clients par project/workspace
  chez le fournisseur. Sinon, il faut continuer la saisie manuelle/CSV.
- Les schemas de reponse exacts peuvent evoluer : le parsing ci-dessous est
  ecrit de facon defensive (plusieurs formes de reponse acceptees) et toute
  erreur HTTP est remontee telle quelle a l'utilisateur pour diagnostic.
"""
import requests
from datetime import datetime, timedelta, timezone


class ProviderSyncError(Exception):
    pass


def _daterange_defaults(days_back):
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    return start, end


def fetch_openai_costs(admin_api_key, days_back=30):
    """
    Renvoie une liste de dicts : {external_id, entry_date (YYYY-MM-DD), amount_usd}
    external_id = OpenAI project_id (ou "default" si absent).
    Documentation : GET https://api.openai.com/v1/organization/costs
    """
    start, end = _daterange_defaults(days_back)
    url = "https://api.openai.com/v1/organization/costs"
    headers = {"Authorization": f"Bearer {admin_api_key}"}
    params = {
        "start_time": int(start.timestamp()),
        "end_time": int(end.timestamp()),
        "bucket_width": "1d",
        "group_by[]": "project_id",
        "limit": 31,
    }

    results = []
    next_page = None
    for _ in range(20):  # garde-fou anti boucle infinie
        if next_page:
            params["page"] = next_page
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        if resp.status_code == 401:
            raise ProviderSyncError("Cle Admin OpenAI invalide ou expiree.")
        if not resp.ok:
            raise ProviderSyncError(f"Erreur OpenAI ({resp.status_code}): {resp.text[:300]}")
        payload = resp.json()

        for bucket in payload.get("data", []):
            bucket_date = datetime.fromtimestamp(
                bucket.get("start_time", start.timestamp()), tz=timezone.utc
            ).date().isoformat()
            for r in bucket.get("results", []):
                amount = r.get("amount") or {}
                value = amount.get("value")
                if value is None:
                    continue
                external_id = r.get("project_id") or "default"
                results.append({
                    "external_id": external_id,
                    "entry_date": bucket_date,
                    "amount_usd": float(value),
                })

        if payload.get("has_more") and payload.get("next_page"):
            next_page = payload["next_page"]
        else:
            break

    return results


def fetch_anthropic_costs(admin_api_key, days_back=30):
    """
    Renvoie une liste de dicts : {external_id, entry_date (YYYY-MM-DD), amount_usd}
    external_id = Anthropic workspace_id (ou "default" si absent, cad
    l'espace de travail par defaut de l'organisation).
    Documentation : GET https://api.anthropic.com/v1/organizations/cost_report
    """
    start, end = _daterange_defaults(days_back)
    url = "https://api.anthropic.com/v1/organizations/cost_report"
    headers = {
        "x-api-key": admin_api_key,
        "anthropic-version": "2023-06-01",
    }
    params = {
        "starting_at": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ending_at": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "group_by[]": "workspace_id",
        "limit": 31,
    }

    results = []
    next_page = None
    for _ in range(20):
        if next_page:
            params["page"] = next_page
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        if resp.status_code == 401:
            raise ProviderSyncError("Cle Admin Anthropic invalide ou expiree.")
        if not resp.ok:
            raise ProviderSyncError(f"Erreur Anthropic ({resp.status_code}): {resp.text[:300]}")
        payload = resp.json()

        for bucket in payload.get("data", []):
            bucket_date = (bucket.get("starting_at") or start.isoformat())[:10]
            for r in bucket.get("results", []):
                raw_amount = r.get("amount")
                if raw_amount is None:
                    continue
                # Anthropic renvoie parfois le montant en cents (chaine),
                # parfois deja en dollars selon l'endpoint/version. On
                # detecte : un entier/chaine sans point -> cents.
                try:
                    amount_num = float(raw_amount)
                except (TypeError, ValueError):
                    continue
                is_cents = isinstance(raw_amount, str) and "." not in raw_amount
                amount_usd = amount_num / 100 if is_cents else amount_num
                external_id = r.get("workspace_id") or "default"
                results.append({
                    "external_id": external_id,
                    "entry_date": bucket_date,
                    "amount_usd": amount_usd,
                })

        if payload.get("has_more") and payload.get("next_page"):
            next_page = payload["next_page"]
        else:
            break

    return results


FETCHERS = {
    "openai": fetch_openai_costs,
    "anthropic": fetch_anthropic_costs,
}
