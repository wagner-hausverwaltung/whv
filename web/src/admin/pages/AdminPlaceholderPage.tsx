import { Alert, Box, Button, Stack, Typography } from "@mui/material";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";

// Stand-in for admin tabs that haven't been ported to the SPA yet. Renders a
// banner pointing at the legacy Jinja UI so the operator can keep working;
// the actual SPA implementation lands in a later commit.
export function AdminPlaceholderPage({
  title,
  legacyPath,
}: {
  title: string;
  legacyPath: string;
}) {
  const legacyUrl = `https://admin.wagner-hausverwaltung.com${legacyPath}`;
  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          {title}
        </Typography>
      </Box>
      <Alert severity="info">
        Diese Seite wird gerade in die neue Admin-Oberfläche überführt. Bis
        dahin nutzen Sie bitte die bisherige Verwalter-Oberfläche.
      </Alert>
      <Box>
        <Button
          component="a"
          href={legacyUrl}
          target="_blank"
          rel="noopener noreferrer"
          variant="contained"
          endIcon={<OpenInNewIcon />}
        >
          {title} (klassische Ansicht öffnen)
        </Button>
      </Box>
    </Stack>
  );
}
