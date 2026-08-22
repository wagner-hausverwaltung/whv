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
