// Shared display + draft helpers for Versorgungsverträge (supplier contracts).

import type {
  SupplierContractBody,
  SupplierContractCategory,
  SupplierContractResponse,
  SupplierContractStatus,
} from "@/api/types";

export interface ContractDraft {
  id: string | null; // null = create
  category: SupplierContractCategory;
  provider_name: string;
  status: SupplierContractStatus;
  contact_id: string | null;
  contract_number: string;
  customer_number: string;
  meter_id: string;
  start_date: string;
  end_date: string;
  cancellation_months: string;
  auto_renew: boolean;
  price: string;
  price_period: "" | "MONATLICH" | "JAEHRLICH";
  notes: string;
}

export const EMPTY_DRAFT: ContractDraft = {
  id: null,
  category: "VERSICHERUNG",
  provider_name: "",
  status: "AKTIV",
  contact_id: null,
  contract_number: "",
  customer_number: "",
  meter_id: "",
  start_date: "",
  end_date: "",
  cancellation_months: "",
  auto_renew: true,
  price: "",
  price_period: "MONATLICH",
  notes: "",
};

export function draftFrom(c: SupplierContractResponse): ContractDraft {
  return {
    id: c.id,
    category: c.category,
    provider_name: c.provider_name,
    status: c.status,
    contact_id: c.contact_id,
    contract_number: c.contract_number ?? "",
    customer_number: c.customer_number ?? "",
    meter_id: c.meter_id ?? "",
    start_date: c.start_date ?? "",
    end_date: c.end_date ?? "",
    cancellation_months: c.cancellation_months != null ? String(c.cancellation_months) : "",
    auto_renew: c.auto_renew ?? true,
    price: c.price != null ? String(c.price) : "",
    price_period: c.price_period ?? "",
    notes: c.notes ?? "",
  };
}

export function bodyFromDraft(d: ContractDraft): SupplierContractBody {
  return {
    category: d.category,
    provider_name: d.provider_name.trim(),
    status: d.status,
    contact_id: d.contact_id,
    contract_number: d.contract_number.trim() || null,
    customer_number: d.customer_number.trim() || null,
    meter_id: d.meter_id || null,
    start_date: d.start_date || null,
    end_date: d.end_date || null,
    cancellation_months: d.cancellation_months ? Number(d.cancellation_months) : null,
    auto_renew: d.auto_renew,
    price: d.price ? Number(d.price.replace(",", ".")) : null,
    price_period: d.price ? d.price_period || null : null,
    notes: d.notes.trim() || null,
  };
}

// Full PUT body straight from a row — for inline edits (status select,
// contact linking) that must not clobber the other fields.
export function bodyFromRow(c: SupplierContractResponse): SupplierContractBody {
  return {
    category: c.category,
    provider_name: c.provider_name,
    status: c.status,
    contact_id: c.contact_id,
    contract_number: c.contract_number,
    customer_number: c.customer_number,
    meter_id: c.meter_id,
    start_date: c.start_date,
    end_date: c.end_date,
    cancellation_months: c.cancellation_months,
    auto_renew: c.auto_renew,
    price: c.price != null ? Number(c.price) : null,
    price_period: c.price_period,
    notes: c.notes,
  };
}

export function fmtContractDate(d: string | null): string {
  if (!d) return "—";
  const [y, m, day] = d.split("-");
  return `${day}.${m}.${y}`;
}

export function fmtPrice(c: SupplierContractResponse): string {
  if (c.price == null) return "—";
  const n = Number(c.price);
  if (!Number.isFinite(n)) return String(c.price);
  const eur = n.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const period =
    c.price_period === "MONATLICH" ? " €/Monat" : c.price_period === "JAEHRLICH" ? " €/Jahr" : " €";
  return `${eur}${period}`;
}
