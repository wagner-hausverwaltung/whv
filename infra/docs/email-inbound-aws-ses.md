# Email-to-ticket via AWS SES inbound — operator setup

This is the one-time AWS setup needed before the backend's
`POST /webhooks/email/inbound` endpoint (Phase 4a-iter2) can ingest emails
sent to `support@wagner-hausverwaltung.com`.

Goal: emails to `support@` create / append to tickets; outbound replies thread
back to the original sender via standard email headers.

## Design at a glance

```
Eigentümer / Mieter
        │ sends email to support@wagner-hausverwaltung.com
        ▼
AWS SES inbound (eu-central-1)
        │ receipt rule: publish to SNS topic whv-email-inbound
        ▼
SNS topic (eu-central-1)
        │ HTTP subscription to https://staging.api.wagner-hausverwaltung.com/webhooks/email/inbound
        ▼
FastAPI webhook handler
        │ verifies SNS signature → parses MIME → looks up ticket from
        │ [#abc12345] in subject (or creates new) → appends message →
        │ fans out emails via Resend (existing outbound path)
```

We're NOT using a Lambda — SNS → HTTPS direct subscription is simpler and
costs the same. If we ever need pre-processing (e.g. S3-stored attachments
> 256 KB) we can insert a Lambda later between SES and SNS.

## Region: eu-central-1 (Frankfurt) — DSGVO

SES is regional. For DSGVO purposes we want the inbound mail data and the
SNS topic in the EU. **Use `eu-central-1` (Frankfurt).** Outbound Resend
already runs in `eu-west-1` (per ADR-0004), so we stay EU-only end-to-end.

Pricing reference (eu-central-1, May 2026):
- SES inbound: $0.10 per 1,000 emails received
- S3 storage (if we enable it later for attachments): standard rates
- SNS HTTPS deliveries: $0.60 per million notifications

For WHV's expected scale (<10k inbound emails/month for years), this is well
under $1/month.

## Step 1 — Verify the domain in SES

We do NOT need to move the whole domain to SES — only delegate inbound for
one subdomain. The marketing site and Bluehost's `info@` mailbox stay
untouched.

1. AWS Console → **Simple Email Service** → switch region to **eu-central-1**.
2. **Identities → Create identity**:
   - Identity type: **Domain**
   - Domain: `wagner-hausverwaltung.com`
   - Leave "Use a default DKIM signing key length (RSA_2048_BIT)" checked.
   - Check "Publish DNS records to Route 53" only if the apex is on Route 53.
     (It isn't — we're on Bluehost. Uncheck it.)
3. SES will show 3 DKIM CNAME records. Copy them to Bluehost DNS:
   - `<token1>._domainkey` → `<token1>.dkim.amazonses.com`
   - `<token2>._domainkey` → `<token2>.dkim.amazonses.com`
   - `<token3>._domainkey` → `<token3>.dkim.amazonses.com`
4. Wait 5–30 minutes for SES to flip "Identity Status" from
   *Verification pending* to *Verified*.

DMARC isn't strictly required for receiving but is a good citizen move:
add a `TXT` record at `_dmarc.wagner-hausverwaltung.com` with value
`v=DMARC1; p=none; rua=mailto:dmarc@wagner-hausverwaltung.com`.

## Step 2 — Pick the inbound subdomain

Don't repoint the apex MX — that would break `info@wagner-hausverwaltung.com`
and the Bluehost-served support@ mailbox. Use a dedicated subdomain so the
two systems coexist:

| Host                                          | Purpose                                |
|-----------------------------------------------|----------------------------------------|
| `wagner-hausverwaltung.com` (apex MX)         | Stays on Bluehost — info@, support@ inbox |
| `inbound.wagner-hausverwaltung.com` (new MX)  | Routed to AWS SES → our webhook       |

Customers will eventually email `support@inbound.wagner-hausverwaltung.com`
once we're confident it works. For the cutover, we'll set up a Bluehost
forward `support@wagner-hausverwaltung.com` → `support@inbound.wagner-hausverwaltung.com`
so the old address keeps working without DNS churn.

### Add the inbound MX

Add an MX record at Bluehost DNS:

| Host       | Type | Priority | Value                                       |
|------------|------|----------|---------------------------------------------|
| `inbound`  | MX   | 10       | `inbound-smtp.eu-central-1.amazonaws.com`   |

Add a verification TXT (SES asks for this when you verify the subdomain):

| Host                    | Type | Value                              |
|-------------------------|------|------------------------------------|
| `_amazonses.inbound`    | TXT  | `<value SES gives you>`            |

Then in SES Console → Identities → Create identity → Domain →
`inbound.wagner-hausverwaltung.com`. Wait for *Verified*.

## Step 3 — Create the SNS topic

1. AWS Console → **SNS** (same region, eu-central-1) → **Topics → Create topic**
2. Type: **Standard**, Name: `whv-email-inbound`
3. After creation, copy the ARN — looks like
   `arn:aws:sns:eu-central-1:<acct>:whv-email-inbound`

## Step 4 — Create the SES receipt rule

1. SES Console → **Email receiving → Rule sets**
2. Either use the default rule set or create one called `whv-inbound-rules`.
   Make sure it's marked **Active**.
3. **Create rule** inside that rule set:
   - Recipient conditions: `support@inbound.wagner-hausverwaltung.com`
     (you can add more recipients later — e.g. `info@inbound.*`)
   - Actions: **Publish to Amazon SNS topic**
     - Topic ARN: pick `whv-email-inbound` from the dropdown
     - Encoding: **UTF-8** (default)
   - Position: top
   - Enabled: yes

SES will offer to add the necessary IAM permission so SES can publish to
the topic — accept it.

## Step 5 — Subscribe our webhook to the SNS topic

This step waits until the backend webhook is deployed (Phase 4a-iter2 code).
The subscription is HTTPS and requires SNS-signature verification, which the
webhook handler will implement.

When the code is live:

1. SNS Console → topic `whv-email-inbound` → **Create subscription**
2. Protocol: **HTTPS**
3. Endpoint: `https://staging.api.wagner-hausverwaltung.com/webhooks/email/inbound`
4. Click **Create subscription**. SNS will send a `SubscriptionConfirmation`
   POST to our webhook — the handler responds by visiting the `SubscribeURL`
   in the payload. The subscription then flips to **Confirmed**.

## Step 6 — Smoke test (after code is live)

```bash
# From any email client, send to support@inbound.wagner-hausverwaltung.com.
# Within ~30s the email should:
#  - appear in the admin UI ticket queue
#  - generate an audit-log entry with action="ticket_created_via_email"
#  - bounce a confirmation email back from noreply@wagner-hausverwaltung.com

# Inspect the webhook log:
ssh whv@46.225.185.151 'cd ~/whv && docker compose -f docker-compose.yml \
  -f docker-compose.staging.yml -f docker-compose.deploy.yml logs --tail=50 backend' \
  | grep email_inbound
```

## Step 7 — Cutover (optional, later)

Once the inbound subdomain works end-to-end, you can either:

- **Option A (recommended): keep two addresses.** Public-facing
  `support@wagner-hausverwaltung.com` (Bluehost mailbox) gets a forward
  rule to `support@inbound.wagner-hausverwaltung.com`. Bluehost mailbox
  becomes a backup only — the forward delivers to SES → ticket system.
- **Option B: full switchover.** Change the apex MX records to point at
  `inbound-smtp.eu-central-1.amazonaws.com` directly. Bluehost mailbox
  becomes unreachable. Higher risk, only do it once everything is
  verified.

## Cost ceiling estimate

For WHV's projected scale (~50 emails inbound/day from owners during a
busy period):

| Item              | Monthly cost estimate                |
|-------------------|--------------------------------------|
| SES inbound       | ~$0.15 (1.5k emails @ $0.10/1k)      |
| SNS HTTPS delivery| ~$0.001                              |
| DKIM / verification| free                                 |
| **Total**         | **< $1/month**                       |

If we later add attachment handling via S3, add ~$0.023/GB/month for
storage and you're still under $5.

## DSGVO check

- All data lives in eu-central-1 (Frankfurt).
- Resend (outbound) is already in eu-west-1 (Dublin) per ADR-0004.
- AWS provides a standard DPA (signable from AWS Artifact in 5 minutes).
- The privacy policy at `https://wagner-hausverwaltung.com/datenschutz`
  needs an addendum mentioning AWS (sub-processor) — write this with the
  legal advisor before going live.

## What you do vs what I do

**You (operator):**
- Steps 1–4 above (SES domain verification, MX, SNS topic, receipt rule)
- AWS Artifact: sign the AWS Data Processing Addendum
- Add AWS as a sub-processor in the Datenschutzerklärung

**Me (next code chunk):**
- New endpoint `POST /webhooks/email/inbound` with SNS signature verification
  + `SubscriptionConfirmation` handling
- MIME parser: extract sender, subject (`[#abc12345]` ref → existing ticket;
  no ref → new ticket), body (strip quoted replies via `talon` / `mail-parser`)
- Schema: `tickets.external_sender_email`, `ticket_messages.source`
  (`PORTAL | EMAIL`), `ticket_messages.email_message_id` (RFC 5322
  `Message-ID` for threading)
- Outbound emails get `Message-ID`, `In-Reply-To`, `References` headers so
  Gmail / Outlook thread correctly
- Idempotency: skip if a `ticket_messages.email_message_id` already matches
- Tests: signature verification, subject parsing, new-ticket creation,
  reply-to-existing-ticket append, unknown-sender path (creates ticket with
  external_sender_email per user choice), idempotency
