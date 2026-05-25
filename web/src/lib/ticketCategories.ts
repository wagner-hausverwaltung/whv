import ChatBubbleOutlineOutlined from "@mui/icons-material/ChatBubbleOutlineOutlined";
import NotificationsOutlined from "@mui/icons-material/NotificationsOutlined";
import AttachFileOutlined from "@mui/icons-material/AttachFileOutlined";
import MenuBookOutlined from "@mui/icons-material/MenuBookOutlined";
import ThumbUpAltOutlined from "@mui/icons-material/ThumbUpAltOutlined";
import PhoneCallbackOutlined from "@mui/icons-material/PhoneCallbackOutlined";
import VpnKeyOutlined from "@mui/icons-material/VpnKeyOutlined";
import PhoneOutlined from "@mui/icons-material/PhoneOutlined";
import CreditCardOutlined from "@mui/icons-material/CreditCardOutlined";
import ReceiptLongOutlined from "@mui/icons-material/ReceiptLongOutlined";
import ContentPasteSearchOutlined from "@mui/icons-material/ContentPasteSearchOutlined";
import AccountBalanceWalletOutlined from "@mui/icons-material/AccountBalanceWalletOutlined";
import HomeOutlined from "@mui/icons-material/HomeOutlined";
import SwapHorizOutlined from "@mui/icons-material/SwapHorizOutlined";
import BuildOutlined from "@mui/icons-material/BuildOutlined";
import BoltOutlined from "@mui/icons-material/BoltOutlined";
import LocalFireDepartmentOutlined from "@mui/icons-material/LocalFireDepartmentOutlined";
import SearchOutlined from "@mui/icons-material/SearchOutlined";
import LightbulbOutlined from "@mui/icons-material/LightbulbOutlined";
import WarningAmberOutlined from "@mui/icons-material/WarningAmberOutlined";
import WaterDropOutlined from "@mui/icons-material/WaterDropOutlined";
import EditOutlined from "@mui/icons-material/EditOutlined";
import ContentCopyOutlined from "@mui/icons-material/ContentCopyOutlined";
import BiotechOutlined from "@mui/icons-material/BiotechOutlined";
import GroupOutlined from "@mui/icons-material/GroupOutlined";
import MoreHorizOutlined from "@mui/icons-material/MoreHorizOutlined";
import type { SvgIconComponent } from "@mui/icons-material";
import type { TicketCategory } from "@/api/types";

// One entry per ticket category. The icon is the MUI component (so the
// SPA can render it directly via <Icon fontSize="small" />); the group
// string matches the GROUPS_ORDER tuple on the backend so the dropdown
// renders in the same order every time.
export interface CategoryMeta {
  group: string;
  icon: SvgIconComponent;
}

export const GROUPS_ORDER = [
  "Allgemeines",
  "Buchhaltung und Zahlungsverkehr",
  "Immobilienvertrieb",
  "Mietverwaltung",
  "Schadensmeldung",
  "WEG Verwaltung",
  "Sonstiges",
] as const;

export const CATEGORY_META: Record<TicketCategory, CategoryMeta> = {
  ALLGEMEIN_FRAGE: { group: "Allgemeines", icon: ChatBubbleOutlineOutlined },
  ALLGEMEIN_KLINGEL: { group: "Allgemeines", icon: NotificationsOutlined },
  ALLGEMEIN_DOKUMENTE: { group: "Allgemeines", icon: AttachFileOutlined },
  ALLGEMEIN_ONBOARDING: { group: "Allgemeines", icon: MenuBookOutlined },
  ALLGEMEIN_LOB: { group: "Allgemeines", icon: ThumbUpAltOutlined },
  ALLGEMEIN_RUECKRUF: { group: "Allgemeines", icon: PhoneCallbackOutlined },
  ALLGEMEIN_SCHLUESSEL: { group: "Allgemeines", icon: VpnKeyOutlined },
  ALLGEMEIN_TELEFONNOTIZ: { group: "Allgemeines", icon: PhoneOutlined },
  BUCHHALTUNG_BANK_SEPA: {
    group: "Buchhaltung und Zahlungsverkehr",
    icon: CreditCardOutlined,
  },
  BUCHHALTUNG_BETRIEBSKOSTEN: {
    group: "Buchhaltung und Zahlungsverkehr",
    icon: ReceiptLongOutlined,
  },
  BUCHHALTUNG_JAHRESABRECHNUNG: {
    group: "Buchhaltung und Zahlungsverkehr",
    icon: MenuBookOutlined,
  },
  BUCHHALTUNG_BELEGE: {
    group: "Buchhaltung und Zahlungsverkehr",
    icon: ContentPasteSearchOutlined,
  },
  BUCHHALTUNG_ABBUCHUNGEN: {
    group: "Buchhaltung und Zahlungsverkehr",
    icon: AccountBalanceWalletOutlined,
  },
  VERTRIEB_BEWERTUNG: { group: "Immobilienvertrieb", icon: HomeOutlined },
  VERTRIEB_BERATUNG: { group: "Immobilienvertrieb", icon: HomeOutlined },
  VERTRIEB_INTERESSE: { group: "Immobilienvertrieb", icon: HomeOutlined },
  MIETER_WECHSEL: { group: "Mietverwaltung", icon: SwapHorizOutlined },
  SCHADEN_ALLGEMEIN: { group: "Schadensmeldung", icon: BuildOutlined },
  SCHADEN_BAUMANGEL: { group: "Schadensmeldung", icon: HomeOutlined },
  SCHADEN_ELEMENTAR: { group: "Schadensmeldung", icon: BoltOutlined },
  SCHADEN_FEUER: {
    group: "Schadensmeldung",
    icon: LocalFireDepartmentOutlined,
  },
  SCHADEN_SCHAEDLINGE: { group: "Schadensmeldung", icon: SearchOutlined },
  SCHADEN_STROM: { group: "Schadensmeldung", icon: LightbulbOutlined },
  SCHADEN_ABWASSER: { group: "Schadensmeldung", icon: WarningAmberOutlined },
  SCHADEN_WASSER: { group: "Schadensmeldung", icon: WaterDropOutlined },
  WEG_ANFRAGE: { group: "WEG Verwaltung", icon: EditOutlined },
  WEG_BESCHLUSSANTRAG: { group: "WEG Verwaltung", icon: ContentCopyOutlined },
  WEG_LEGIONELLEN: { group: "WEG Verwaltung", icon: BiotechOutlined },
  SONSTIGES_DATEN: { group: "Sonstiges", icon: EditOutlined },
  SONSTIGES_BESCHLUSSUMSETZUNG: { group: "Sonstiges", icon: BuildOutlined },
  SONSTIGES_ETV: { group: "Sonstiges", icon: GroupOutlined },
  SONSTIGES_RELAY: { group: "Sonstiges", icon: BuildOutlined },
  SONSTIGES_STOERUNG: { group: "Sonstiges", icon: WarningAmberOutlined },
  SONSTIGES_OTHER: { group: "Sonstiges", icon: MoreHorizOutlined },
};

// Returns the (group, [category, ...]) pairs in the canonical GROUPS_ORDER
// so the create-ticket dropdown and the admin filter chips render the same
// way everywhere.
export function groupedCategories(): { group: string; items: TicketCategory[] }[] {
  const buckets = new Map<string, TicketCategory[]>();
  for (const [cat, meta] of Object.entries(CATEGORY_META) as [
    TicketCategory,
    CategoryMeta,
  ][]) {
    if (!buckets.has(meta.group)) buckets.set(meta.group, []);
    buckets.get(meta.group)!.push(cat);
  }
  return GROUPS_ORDER.filter((g) => buckets.has(g)).map((g) => ({
    group: g,
    items: buckets.get(g)!,
  }));
}
