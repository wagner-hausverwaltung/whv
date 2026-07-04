// Shared display helpers for Versorgungsverträge (supplier contracts).

import type { SupplierContractResponse } from "@/api/types";

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
