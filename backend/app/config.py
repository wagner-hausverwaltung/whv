from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Sentinel default for `jwt_secret`. Outside dev the app refuses to boot
# while this (or an empty string) is the effective value — a publicly
# known signing key would let anyone forge a VERWALTER access token.
# Enforced by Settings._require_real_jwt_secret below.
DEFAULT_JWT_SECRET = "change-me-in-prod"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Look in cwd and one level up so the same .env works whether you
        # run from the repo root or from backend/.
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: Literal["dev", "staging", "prod"] = "dev"
    log_level: str = "INFO"

    database_url: str = Field(
        default="postgresql+asyncpg://whv:whv@localhost:5432/whv",
        description="Async DSN for Postgres",
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )

    # Default points at the prod-replica dev instance Impower gave us
    # for staging — that's the only URL we have verified to respond to
    # our test JWT. Production cutover will replace this with whatever
    # Impower hands over on go-live; staging's .env override stays the
    # source of truth either way. `api.app.impower.de/v2/d` (the
    # original placeholder) does not exist + 404s on every path; do
    # not put it back.
    impower_api_base: str = "https://api.prod-replica.develop.impower.de/v2"
    impower_api_token: str = ""
    # Shared secret for verifying inbound POST /webhooks/impower payloads.
    # Impower signs the raw request body with HMAC-SHA256 and sends the
    # hex digest in `X-Impower-Signature`. We recompute and compare in
    # constant time before processing. Empty disables verification (dev
    # convenience — never deploy to prod without it set).
    impower_webhook_secret: str = ""

    resend_api_key: str = ""
    email_from_address: str = "noreply@wagner-hausverwaltung.com"
    email_from_name: str = "Wagner Hausverwaltung"
    # Address that SES is configured to receive at. Set as Reply-To on
    # ticket notification emails so a recipient who hits "Reply" lands
    # back on the SES inbound rule → /webhooks/email/inbound, and never
    # has to touch the portal to respond. Empty in dev — leave the
    # header unset so we don't direct staging replies into a void.
    email_inbound_address: str = ""

    jwt_secret: str = DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30
    password_reset_ttl_minutes: int = 30

    # Absolute origin of the public web portal (SPA). Used as the allowed
    # CORS origin for SPA requests and as the base for clickable reset
    # links in password-reset emails. The same SPA bundle hosts both the
    # customer portal and the Verwalter admin under /admin/*.
    portal_base_url: str = "http://localhost:5173"
    # Optional second CORS origin: the admin host serves the same SPA but
    # via a different DNS name (admin.wagner-hausverwaltung.com vs.
    # portal.wagner-hausverwaltung.com). When set, it joins portal_base_url
    # in the CORS allow-list. Empty in dev (single Vite origin).
    admin_base_url: str = ""

    # AWS SES inbound email pipeline. The SES receipt rule saves the full MIME
    # to s3://{s3_inbound_bucket}/{messageId} and publishes a notification to
    # SNS; the webhook handler fetches the body from S3 (since "Publish to SNS"
    # action caps at 150 KB — too small for any Outlook email with a signature).
    # Credentials use a dedicated IAM user scoped to the inbound bucket only.
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    s3_inbound_bucket: str = ""
    s3_inbound_region: str = "eu-central-1"

    # Where the Celery result-PDF task writes Umlaufbeschluss protocols on
    # disk. Phase 1 stores PDFs locally; §1.4d iter 2 will switch to Hetzner
    # Object Storage and replace this with bucket config. The dir is created
    # on first write — no need to provision it ahead of time.
    resolution_pdf_dir: str = "/var/lib/whv/resolutions"

    # User-uploaded avatar images. Stored as PNG (Pillow normalises every
    # upload to keep the static-mount URL stable). Same Hetzner-OS migration
    # path as resolution PDFs in §1.4d iter 2.
    avatar_dir: str = "/var/lib/whv/avatars"
    # Max size of an uploaded avatar in bytes. 4 MB is plenty for a face
    # photo; we resize down to 256x256 anyway before saving.
    avatar_max_bytes: int = 4 * 1024 * 1024

    # Verwalter-uploaded property hero photos. PNG, fit into a 1280x960 box
    # so they look sharp on retina but don't waste 4K pixels for what's at
    # most a 600px card. Local disk for v1; Hetzner OS later.
    property_image_dir: str = "/var/lib/whv/property-images"
    property_image_max_bytes: int = 10 * 1024 * 1024

    # Verwalter-uploaded property documents (PDFs etc.) — Item 6. Stored
    # under {document_dir}/{document_id}.{ext}, served via an authenticated
    # FileResponse endpoint (NOT StaticFiles — visibility scope matters,
    # and a UUIDv7 path is guessable enough that we don't want public reads).
    document_dir: str = "/var/lib/whv/documents"
    # 50 MB is the practical cap for PDFs (Jahresabrechnungen scanned at
    # 300 DPI run 10-30 MB; protocols with photo appendices push the rest).
    document_max_bytes: int = 50 * 1024 * 1024

    # Ticket message attachments — Item 7. SPA uploads + inbound-email
    # MIME parts land here. Smaller cap than documents: most attachments
    # are phone photos or invoice PDFs and 25 MB matches the SES inbound
    # limit, so files that arrived via email always fit through the SPA
    # too. Auth-gated download endpoint (NOT StaticFiles).
    ticket_attachment_dir: str = "/var/lib/whv/ticket-attachments"
    ticket_attachment_max_bytes: int = 25 * 1024 * 1024

    # Announcement (Mitteilung) attachments — typically a meeting
    # protocol PDF or a photo of an outage / damage notice. Same 25 MB
    # cap and storage convention as ticket attachments; auth-gated
    # download via the admin + owner API.
    announcement_attachment_dir: str = "/var/lib/whv/announcement-attachments"
    announcement_attachment_max_bytes: int = 25 * 1024 * 1024

    # ETV agenda-item attachments — supporting docs (Angebotsvergleiche,
    # Baupläne, Vergleichsangebote) shown inline next to a
    # Tagesordnungspunkt. Same 25 MB cap, same storage convention,
    # same auth-gated download as the announcement variant.
    etv_attachment_dir: str = "/var/lib/whv/etv-attachments"
    etv_attachment_max_bytes: int = 25 * 1024 * 1024

    # Meter-reading photos (Zählerstand-Fotos, ADR-0016) — a phone snap of
    # the meter face, OCR'd to pre-fill the value. Images only; 15 MB
    # comfortably covers a HEIC/JPEG from a modern phone. Same
    # `local-disk:<suffix>` convention + auth-gated download as the other
    # attachment dirs; moves to Hetzner OS on the same wave.
    meter_reading_photo_dir: str = "/var/lib/whv/meter-readings"
    meter_reading_photo_max_bytes: int = 15 * 1024 * 1024

    # Signed Eigentümerversammlung protocol PDFs — one per assembly,
    # named {assembly_id}.pdf so re-uploads cleanly overwrite. Auth-
    # gated download via /me/assemblies/{id}/protocol; storage moves
    # to Hetzner OS on the same wave as the other dirs.
    etv_protocol_dir: str = "/var/lib/whv/etv-protocols"
    # Protocols can run long (multi-MB if photos + sketch appendices
    # are inlined), so we use the document cap rather than the
    # attachment one.
    etv_protocol_max_bytes: int = 50 * 1024 * 1024

    # Verwalter-uploaded ETV invitation PDFs — one per assembly,
    # named {assembly_id}.pdf so re-uploads cleanly overwrite. Drives
    # the LLM extraction (ADR-0008): on upload the assembly's
    # `invitation_pdf_url` flips + an extract_etv_metadata task is
    # enqueued. Auth-gated download via /me/assemblies/{id}/invitation
    # so owners + iOS can fetch it too. Same Hetzner OS migration as
    # the protocol dir.
    etv_invitation_dir: str = "/var/lib/whv/etv-invitations"
    # Same envelope as protocols — invitations sometimes pack the
    # Tagesordnung + Anlagen + Hausordnung-Auszüge into one file and
    # can run into the tens of MB.
    etv_invitation_max_bytes: int = 50 * 1024 * 1024

    # APNs push notifications (token-based auth, ADR-0010). Empty
    # apns_key_p8 → the push service short-circuits to a no-op,
    # mirroring how an empty Resend key disables email. So staging
    # without the key configured simply doesn't push; the rest of
    # the request path is unaffected.
    #
    #   apns_key_p8   — the .p8 auth-key contents (PEM). We take the
    #                   contents (not a path) so it can live in the
    #                   .env / secret manager like every other secret.
    #   apns_key_id   — the 10-char Key ID shown next to the key in
    #                   the Developer Portal.
    #   apns_team_id  — the 10-char Apple Team ID (Membership page).
    #   apns_bundle_id— the app bundle id; becomes the APNs `topic`
    #                   header. Defaults to the prod bundle id.
    #   apns_use_sandbox — true routes to api.development.push.apple.com
    #                   (dev builds installed via Xcode / debug).
    #                   false → api.push.apple.com (TestFlight + App
    #                   Store). A device token is environment-specific,
    #                   so this must match the build the token came
    #                   from.
    apns_key_p8: str = ""
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_bundle_id: str = "com.wagner-hausverwaltung.portal"
    apns_use_sandbox: bool = True

    # DocuSeal e-signature (ADR-0012). Empty `docuseal_api_key` →
    # DocuSealClient.is_configured is False; the create endpoint 503s
    # and the feature ships dark until the self-hosted instance exists.
    # `docuseal_webhook_secret` HMAC-verifies the completion webhook.
    docuseal_base_url: str = ""
    docuseal_api_key: str = ""
    docuseal_webhook_secret: str = ""

    # LLM extraction pipeline (ADR-0008). One API key per provider,
    # selected by `llm_provider`. Empty key → factory raises rather
    # than silently no-op — extraction tasks then short-circuit with
    # a clear error in the audit log.
    llm_provider: Literal["gemini", "none"] = "gemini"
    gemini_api_key: str = ""
    # Default model is Gemini 2.0 Flash — cheap (~$0.001 per 10-page
    # PDF), German-strong, native multimodal. Bump to gemini-2.0-pro
    # via env override for tougher cases without code changes.
    gemini_model: str = "gemini-flash-latest"
    # Hard cap so a misconfigured prompt template can't run away with
    # the budget. Default is set for the protocol-extraction path,
    # which is the densest output we generate (Beschluss texts +
    # discussion entries per TOP). 8 KB was too tight — Gemini
    # truncated mid-string. 32 KB fits even multi-TOP protocols with
    # plenty of margin; Gemini 2.5 Flash supports up to 65 K.
    llm_max_output_tokens: int = 32768

    # --- RAG assistant (ADR-0013) -------------------------------------
    # Off by default: the assistant ships dark until the vector store +
    # ingestion exist and the ACL cross-user red-team test passes.
    # rag_enabled=true makes the backend init + bootstrap the pgvector
    # store on boot (lifespan) and (later) expose /assistant/*.
    rag_enabled: bool = False
    # Async DSN for the SEPARATE pgvector store (the `vectordb`
    # container) — NOT the app database. Empty in plain local runs;
    # docker-compose sets it. OCR text + chunk embeddings live here.
    rag_database_url: str = ""
    # Google embedding model — same API key + AVV as Gemini generation
    # (`gemini_api_key`). gemini-embedding-001 is the current model served on
    # v1beta; the legacy embedding-001 / text-embedding-004 were retired and
    # now 404 ("not found for API version v1beta"). It emits 3072 dims by
    # default — the provider requests output_dimensionality=EMBEDDING_DIM (768)
    # so vectors fit app/rag/constants.EMBEDDING_DIM and the pgvector column.
    # Note: only embedContent (single) is supported, not batchEmbedContents.
    rag_embedding_model: str = "models/gemini-embedding-001"
    # Retrieval knobs: top_k chunks handed to the generator; min_similarity
    # is the abstain threshold (cosine) — below it the assistant answers
    # "Dazu habe ich nichts gefunden" instead of guessing (ADR-0013).
    rag_retrieval_top_k: int = 8
    rag_min_similarity: float = 0.35

    @model_validator(mode="after")
    def _require_real_jwt_secret(self) -> Self:
        # In staging/prod a forgeable signing key is a critical hole: with the
        # default (or empty) secret anyone can mint a VERWALTER access token and
        # impersonate any user. Refuse to boot rather than silently trust forged
        # JWTs. Dev keeps the convenient default so local runs + tests need no
        # extra setup.
        if self.app_env != "dev" and self.jwt_secret in ("", DEFAULT_JWT_SECRET):
            raise ValueError(
                "jwt_secret must be set to a strong, non-default value when "
                f"app_env={self.app_env!r}; refusing to boot with the default "
                "or empty signing key."
            )
        return self

    @model_validator(mode="after")
    def _require_safe_cors_in_prod(self) -> Self:
        # The CORS allow-list (portal_base_url + admin_base_url) feeds
        # straight into Access-Control-Allow-Origin. A leftover localhost or
        # plain-http origin in prod would either break the real SPA or open
        # the API to an http origin, so refuse to boot until they're real
        # https hosts. Dev/staging keep the convenient localhost defaults.
        if self.app_env != "prod":
            return self
        origins = [self.portal_base_url]
        if self.admin_base_url:
            origins.append(self.admin_base_url)
        for origin in origins:
            if not origin.startswith("https://") or "localhost" in origin or "127.0.0.1" in origin:
                raise ValueError(
                    f"CORS origin {origin!r} is not allowed in prod: origins must be "
                    "https and non-localhost (check portal_base_url / admin_base_url)."
                )
        return self

    @model_validator(mode="after")
    def _require_rag_store_when_enabled(self) -> Self:
        # A half-enabled assistant (feature on, no store DSN) would 500 on
        # the first query rather than fail at boot. Refuse to start instead.
        if self.rag_enabled and not self.rag_database_url:
            raise ValueError("rag_enabled=true requires rag_database_url (the pgvector store DSN).")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
