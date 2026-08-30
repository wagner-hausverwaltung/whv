// Fahrtenbuch display helpers shared by the admin page and the edit dialog.

const PURPOSE_LABEL: Record<string, string> = {
  BESICHTIGUNG: "Besichtigung",
  ETV: "Eigentümerversammlung",
  HANDWERKERTERMIN: "Handwerkertermin",
  EIGENTUEMERTERMIN: "Eigentümertermin",
  BUERO: "Büro",
  SONSTIGES: "Sonstiges",
  PRIVAT: "Privat",
};

export function purposeLabel(p: string | null | undefined): string {
  if (!p) return "offen";
  return PURPOSE_LABEL[p] ?? p;
}

/** Decode a Google-encoded polyline (precision 1e-5) into [lat, lng] pairs. */
export function decodePolyline(encoded: string): [number, number][] {
  const out: [number, number][] = [];
  let index = 0;
  let lat = 0;
  let lng = 0;
  while (index < encoded.length) {
    for (const which of ["lat", "lng"] as const) {
      let result = 0;
      let shift = 0;
      let b: number;
      do {
        b = encoded.charCodeAt(index++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20);
      const delta = result & 1 ? ~(result >> 1) : result >> 1;
      if (which === "lat") lat += delta;
      else lng += delta;
    }
    out.push([lat / 1e5, lng / 1e5]);
  }
  return out;
}
