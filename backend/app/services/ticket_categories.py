"""Static metadata for the 32 ticket categories (casavi taxonomy).

`CATEGORY_META[cat]` returns a dict with `group`, `label_de`, `label_en`,
and `icon` (an MUI icon name; the SPA imports it from
@mui/icons-material at render time). Kept on the backend so the same
labels show up in admin tables, emails, and audit-log payloads without
the SPA being the source of truth.

The groups appear in this fixed order on the create form's grouped Select
dropdown so the Verwalter / Eigentümer learns to expect them in the same
place every time.
"""

from typing import Final, TypedDict

from app.models import TicketCategory


class CategoryMeta(TypedDict):
    group: str
    label_de: str
    label_en: str
    icon: str  # MUI icon name (component imported by the SPA)


GROUPS_ORDER: Final[tuple[str, ...]] = (
    "Allgemeines",
    "Buchhaltung und Zahlungsverkehr",
    "Immobilienvertrieb",
    "Mietverwaltung",
    "Schadensmeldung",
    "WEG Verwaltung",
    "Sonstiges",
)


CATEGORY_META: Final[dict[TicketCategory, CategoryMeta]] = {
    TicketCategory.ALLGEMEIN_FRAGE: {
        "group": "Allgemeines",
        "label_de": "Allgemeine Frage / Information",
        "label_en": "General question / information",
        "icon": "ChatBubbleOutlineOutlined",
    },
    TicketCategory.ALLGEMEIN_KLINGEL: {
        "group": "Allgemeines",
        "label_de": "Änderung Klingel-/Namensschild",
        "label_en": "Doorbell / name plate change",
        "icon": "NotificationsOutlined",
    },
    TicketCategory.ALLGEMEIN_DOKUMENTE: {
        "group": "Allgemeines",
        "label_de": "Anforderung von Dokumenten",
        "label_en": "Document request",
        "icon": "AttachFileOutlined",
    },
    TicketCategory.ALLGEMEIN_ONBOARDING: {
        "group": "Allgemeines",
        "label_de": "Ihr Onboarding zur Hausverwaltung",
        "label_en": "Onboarding to property management",
        "icon": "MenuBookOutlined",
    },
    TicketCategory.ALLGEMEIN_LOB: {
        "group": "Allgemeines",
        "label_de": "Lob & Kritik",
        "label_en": "Praise & criticism",
        "icon": "ThumbUpAltOutlined",
    },
    TicketCategory.ALLGEMEIN_RUECKRUF: {
        "group": "Allgemeines",
        "label_de": "Rückrufbitte",
        "label_en": "Callback request",
        "icon": "PhoneCallbackOutlined",
    },
    TicketCategory.ALLGEMEIN_SCHLUESSEL: {
        "group": "Allgemeines",
        "label_de": "Schlüssel-/Schließzylinderbestellung",
        "label_en": "Key / lock cylinder order",
        "icon": "VpnKeyOutlined",
    },
    TicketCategory.ALLGEMEIN_TELEFONNOTIZ: {
        "group": "Allgemeines",
        "label_de": "Telefonnotiz",
        "label_en": "Phone note",
        "icon": "PhoneOutlined",
    },
    TicketCategory.BUCHHALTUNG_BANK_SEPA: {
        "group": "Buchhaltung und Zahlungsverkehr",
        "label_de": "Änderung der Bankverbindung / SEPA-Lastschriftmandat",
        "label_en": "Bank account change / SEPA mandate",
        "icon": "CreditCardOutlined",
    },
    TicketCategory.BUCHHALTUNG_BETRIEBSKOSTEN: {
        "group": "Buchhaltung und Zahlungsverkehr",
        "label_de": "Anfrage zur Betriebskostenabrechnung",
        "label_en": "Operating costs statement enquiry",
        "icon": "ReceiptLongOutlined",
    },
    TicketCategory.BUCHHALTUNG_JAHRESABRECHNUNG: {
        "group": "Buchhaltung und Zahlungsverkehr",
        "label_de": "Anfrage zur Jahresabrechnung",
        "label_en": "Annual statement enquiry",
        "icon": "MenuBookOutlined",
    },
    TicketCategory.BUCHHALTUNG_BELEGE: {
        "group": "Buchhaltung und Zahlungsverkehr",
        "label_de": "Belegprüfung",
        "label_en": "Receipt review",
        "icon": "ContentPasteSearchOutlined",
    },
    TicketCategory.BUCHHALTUNG_ABBUCHUNGEN: {
        "group": "Buchhaltung und Zahlungsverkehr",
        "label_de": "Rückfragen zu Abbuchungen",
        "label_en": "Questions about direct debits",
        "icon": "AccountBalanceWalletOutlined",
    },
    TicketCategory.VERTRIEB_BEWERTUNG: {
        "group": "Immobilienvertrieb",
        "label_de": "Anfrage zur Immobilienbewertung",
        "label_en": "Property valuation enquiry",
        "icon": "HomeOutlined",
    },
    TicketCategory.VERTRIEB_BERATUNG: {
        "group": "Immobilienvertrieb",
        "label_de": "Beratungsgespräch",
        "label_en": "Consultation",
        "icon": "HomeOutlined",
    },
    TicketCategory.VERTRIEB_INTERESSE: {
        "group": "Immobilienvertrieb",
        "label_de": "Kauf-/Mietinteresse",
        "label_en": "Buy / rent interest",
        "icon": "HomeOutlined",
    },
    TicketCategory.MIETER_WECHSEL: {
        "group": "Mietverwaltung",
        "label_de": "Mieterwechsel",
        "label_en": "Tenant change",
        "icon": "SwapHorizOutlined",
    },
    TicketCategory.SCHADEN_ALLGEMEIN: {
        "group": "Schadensmeldung",
        "label_de": "Allgemeine Schadensmeldung",
        "label_en": "General damage report",
        "icon": "BuildOutlined",
    },
    TicketCategory.SCHADEN_BAUMANGEL: {
        "group": "Schadensmeldung",
        "label_de": "Baumangel",
        "label_en": "Construction defect",
        "icon": "HomeOutlined",
    },
    TicketCategory.SCHADEN_ELEMENTAR: {
        "group": "Schadensmeldung",
        "label_de": "Elementarschaden",
        "label_en": "Natural-event damage",
        "icon": "BoltOutlined",
    },
    TicketCategory.SCHADEN_FEUER: {
        "group": "Schadensmeldung",
        "label_de": "Feuer-/Brandschaden",
        "label_en": "Fire damage",
        "icon": "LocalFireDepartmentOutlined",
    },
    TicketCategory.SCHADEN_SCHAEDLINGE: {
        "group": "Schadensmeldung",
        "label_de": "Schädlingsbekämpfung",
        "label_en": "Pest control",
        "icon": "SearchOutlined",
    },
    TicketCategory.SCHADEN_STROM: {
        "group": "Schadensmeldung",
        "label_de": "Strom-/Elektrikschaden",
        "label_en": "Electrical damage",
        "icon": "LightbulbOutlined",
    },
    TicketCategory.SCHADEN_ABWASSER: {
        "group": "Schadensmeldung",
        "label_de": "Verstopfung / Rückstau Abwasser",
        "label_en": "Drain blockage / sewage backup",
        "icon": "WarningAmberOutlined",
    },
    TicketCategory.SCHADEN_WASSER: {
        "group": "Schadensmeldung",
        "label_de": "Wasserschaden",
        "label_en": "Water damage",
        "icon": "WaterDropOutlined",
    },
    TicketCategory.WEG_ANFRAGE: {
        "group": "WEG Verwaltung",
        "label_de": "Anfrage an die WEG-Verwaltung",
        "label_en": "Enquiry to WEG management",
        "icon": "EditOutlined",
    },
    TicketCategory.WEG_BESCHLUSSANTRAG: {
        "group": "WEG Verwaltung",
        "label_de": "Antrag zur Tagesordnung / Beschlussantrag",
        "label_en": "Agenda item / resolution motion",
        "icon": "ContentCopyOutlined",
    },
    TicketCategory.WEG_LEGIONELLEN: {
        "group": "WEG Verwaltung",
        "label_de": "Legionellenprüfung",
        "label_en": "Legionella inspection",
        "icon": "BiotechOutlined",
    },
    TicketCategory.SONSTIGES_DATEN: {
        "group": "Sonstiges",
        "label_de": "Änderung der Daten im Kundenportal",
        "label_en": "Customer-portal data change",
        "icon": "EditOutlined",
    },
    TicketCategory.SONSTIGES_BESCHLUSSUMSETZUNG: {
        "group": "Sonstiges",
        "label_de": "Beschlussumsetzung",
        "label_en": "Resolution execution",
        "icon": "BuildOutlined",
    },
    TicketCategory.SONSTIGES_ETV: {
        "group": "Sonstiges",
        "label_de": "Eigentümerversammlung",
        "label_en": "Owners' meeting",
        "icon": "GroupOutlined",
    },
    TicketCategory.SONSTIGES_RELAY: {
        "group": "Sonstiges",
        "label_de": "Relay-Meldung",
        "label_en": "Relay notification",
        "icon": "BuildOutlined",
    },
    TicketCategory.SONSTIGES_STOERUNG: {
        "group": "Sonstiges",
        "label_de": "Störung",
        "label_en": "Disturbance",
        "icon": "WarningAmberOutlined",
    },
    TicketCategory.SONSTIGES_OTHER: {
        "group": "Sonstiges",
        "label_de": "Sonstiges",
        "label_en": "Other",
        "icon": "MoreHorizOutlined",
    },
}


# Default category used when an email arrives without a clear ticket-ref
# in the subject line. SONSTIGES_OTHER is the catch-all.
DEFAULT_CATEGORY: Final[TicketCategory] = TicketCategory.SONSTIGES_OTHER


def label(cat: TicketCategory, locale: str = "de") -> str:
    """Convenience accessor for short label by locale (de | en)."""
    meta = CATEGORY_META[cat]
    return meta["label_en"] if locale == "en" else meta["label_de"]
