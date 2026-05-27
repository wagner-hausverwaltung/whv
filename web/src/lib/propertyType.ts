/// Translate Impower's `PropertyDto.type` enum into the German labels
/// Wagner Hausverwaltung uses in correspondence + UI:
///
///   OWNER  → WEG  (Wohnungseigentümergemeinschaft / Hausverwaltung)
///   RENTAL → MV   (Mietverwaltung)
///   STRATA → SEV  (Sondereigentumsverwaltung)
///
/// Falls back to the raw string for any unexpected value so we never
/// show an empty cell — the synced property name almost always
/// carries the type prefix anyway.
export function propertyTypeLabel(type: string): string {
  switch (type) {
    case "OWNER":
      return "WEG";
    case "RENTAL":
      return "MV";
    case "STRATA":
      return "SEV";
    default:
      return type;
  }
}

/// "Does this property type make MEA / Miteigentumsanteile meaningful?"
/// WEG and SEV both carry ownership shares; MV (rental) properties
/// don't — Mieter have no Anteile, so showing a MEA column on
/// /properties/:id for an MV is just visual noise.
export function propertyHasOwnershipShares(type: string): boolean {
  return type === "OWNER" || type === "STRATA";
}
