// Legal footer — required by §5 TMG (Impressum) + Art. 13 DSGVO
// (Datenschutzerklärung). Same content on both authenticated and
// pre-auth pages so the links are always reachable.

const LEGAL_LINKS = [
  { label: "Impressum", href: "https://wagner-hausverwaltung.com/impressum" },
  {
    label: "Datenschutzerklärung",
    href: "https://wagner-hausverwaltung.com/datenschutz",
  },
  {
    label: "Cookie-Richtlinie (EU)",
    href: "https://wagner-hausverwaltung.com/cookie",
  },
];

export function Footer() {
  return (
    <footer className="border-t border-whv-border bg-white">
      <div className="max-w-5xl mx-auto px-6 py-5 muted text-xs space-y-3">
        <p>
          Staufeneckstraße 17, 70469 Stuttgart, Baden-Württemberg, Deutschland
          {" · "}Mobil:{" "}
          <a href="tel:+4915679127579" className="hover:underline">
            +49 15679 127579
          </a>
          {" · "}E-Mail:{" "}
          <a
            href="mailto:info@wagner-hausverwaltung.com"
            className="hover:underline"
          >
            info@wagner-hausverwaltung.com
          </a>
          {" · "}HRB 793472 Amtsgericht Stuttgart{" · "}St-Nr. 99032/25628
          Finanzamt Stuttgart{" · "}USt-ID: DE367079394
        </p>
        <p className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span>© 2026 Wagner Hausverwaltung</span>
          {LEGAL_LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline"
            >
              {link.label}
            </a>
          ))}
        </p>
      </div>
    </footer>
  );
}
