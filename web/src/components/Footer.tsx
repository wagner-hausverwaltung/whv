import { Box, Container, Link, Stack, Typography } from "@mui/material";

// Legal footer — required by §5 TMG (Impressum) + Art. 13 DSGVO
// (Datenschutzerklärung). Same content on both authenticated and pre-auth
// pages so the links are always reachable. Stays German-only; the contact
// data is identical regardless of UI language.

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
    <Box
      component="footer"
      sx={{
        borderTop: 1,
        borderColor: "divider",
        bgcolor: "background.paper",
      }}
    >
      <Container maxWidth="lg" sx={{ py: 2.5 }}>
        <Stack spacing={1.25} sx={{ alignItems: "center", textAlign: "center" }}>
          <Typography variant="caption" color="text.secondary">
            Staufeneckstraße 17, 70469 Stuttgart, Baden-Württemberg, Deutschland
            {" · "}Mobil:{" "}
            <Link href="tel:+4915679127579" color="inherit" underline="hover">
              +49 15679 127579
            </Link>
            {" · "}E-Mail:{" "}
            <Link
              href="mailto:info@wagner-hausverwaltung.com"
              color="inherit"
              underline="hover"
            >
              info@wagner-hausverwaltung.com
            </Link>
            {" · "}HRB 793472 Amtsgericht Stuttgart{" · "}St-Nr. 99032/25628
            Finanzamt Stuttgart{" · "}USt-ID: DE367079394
          </Typography>
          <Stack
            direction="row"
            spacing={2}
            useFlexGap
            sx={{ flexWrap: "wrap", justifyContent: "center", rowGap: 0.5 }}
          >
            <Typography variant="caption" color="text.secondary">
              © 2026 Wagner Hausverwaltung
            </Typography>
            {LEGAL_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                target="_blank"
                rel="noopener noreferrer"
                variant="caption"
                color="text.secondary"
                underline="hover"
              >
                {link.label}
              </Link>
            ))}
          </Stack>
        </Stack>
      </Container>
    </Box>
  );
}
