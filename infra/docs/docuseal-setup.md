# DocuSeal e-signature — setup runbook (ADR-0012)

The signing feature ships **dark**: empty `DOCUSEAL_API_KEY` on the
backend ⇒ the create endpoint 503s and the admin tab hides. It activates
the moment the three env vars below are set. This runbook is the
one-time infra Luis provisions; the code is built in parallel.

Division of labour:
- **Luis (infra):** steps 1–5 below — DNS, SES, DocuSeal deploy, API
  token + webhook, backend env.
- **Claude (code):** `signature_requests` model + migration, the
  `SIGNATUR` document kind, `POST/GET /admin/signature-requests`, the
  HMAC-verified `POST /webhooks/docuseal`, and the admin "Signaturen"
  tab. All gated; safe to merge before the instance exists.

---

## 1. DNS

Add an **A record** `sign.wagner-hausverwaltung.com → <Hetzner host IP>`
(same host that runs the app stack). DNS for the domain lives at
**Bluehost** (the marketing site host) unless delegated elsewhere.

## 2. AWS SES (send signing mails as wagner-hausverwaltung)

1. **Verify the sending domain** `wagner-hausverwaltung.com` in SES
   (Configuration ▸ Identities ▸ Create identity ▸ Domain). SES gives 3
   **DKIM CNAME** records — add them at **Bluehost DNS**. (Optionally a
   custom MAIL FROM subdomain + its MX/SPF.)
2. **Request production access** (SES starts in *sandbox* — sandbox can
   only mail verified addresses, useless for real signers). Account ▸
   *Request production access*; approval is usually quick.
3. **Create SMTP credentials** (SES ▸ SMTP settings ▸ *Create SMTP
   credentials*). You get an SMTP **username + password** and the
   regional host, e.g. `email-smtp.eu-central-1.amazonaws.com`.

> SNS isn't required for this feature. (It's only used if you later wire
> SES bounce/complaint notifications — out of scope here.)

## 3. Deploy DocuSeal (Hetzner)

```sh
# on the Hetzner host
git pull                      # gets infra/docuseal/
cd <repo>/infra/docuseal
cp .env.example .env
#  → DOCUSEAL_SECRET_KEY_BASE = openssl rand -hex 64
#  → SES_SMTP_HOST / USERNAME / PASSWORD from step 2
docker compose up -d
```

Add the `sign.` vhost to the host's Caddy (see
`infra/docuseal/Caddyfile.snippet`) and reload Caddy. Open
`https://sign.wagner-hausverwaltung.com`, create the **first admin
user**, and send a test signing email to yourself to confirm SES works.

## 4. DocuSeal API token + webhook

In DocuSeal (Settings ▸ API):
1. Copy the **API token**.
2. Add a **webhook** → URL
   `https://staging.api.wagner-hausverwaltung.com/webhooks/docuseal`,
   event **`form.completed`**. Set a **signing secret** (any strong
   random string) — DocuSeal signs the webhook so we can HMAC-verify it.

## 5. Backend env

Set on the staging backend (and prod later):

```
DOCUSEAL_BASE_URL=https://sign.wagner-hausverwaltung.com/api
DOCUSEAL_API_KEY=<token from step 4.1>
DOCUSEAL_WEBHOOK_SECRET=<secret from step 4.2>
```

Redeploy the backend. `DocuSealClient.is_configured` flips to True; the
admin "Signaturen" tab appears and `POST /admin/signature-requests`
starts working.

---

## End-to-end test (together)

Once 1–5 are done: in the admin, open **Signaturen ▸ Neue Signatur**,
upload a PDF, pick a recipient (or free-text name+email), submit. The
signer gets an SES email from `noreply@wagner-hausverwaltung.com`, signs
on the DocuSeal page, and the signed PDF lands back in WHV documents
(kind **SIGNATUR**) with the request flipped to **COMPLETED**.

> The DocuSeal API shapes in `app/integrations/docuseal/client.py` follow
> the documented public API; if the deployed version differs, that one
> file (+ the webhook parser) is where we adjust.
