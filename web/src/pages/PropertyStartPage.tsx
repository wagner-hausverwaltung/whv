import AddIcon from "@mui/icons-material/Add";
import { Box, Button, Card, CardActionArea, Stack, Typography } from "@mui/material";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";

/**
 * "Start" — the property workspace landing tab (the default after login /
 * property switch). A light overview: the primary "Neues Ticket" action plus
 * quick-nav cards to the other sections. Kept data-free for now (the property
 * header sits above the tabs); can be enriched later with live summary cards
 * (next ETV, open tickets, latest Mitteilung).
 */
export function PropertyStartPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { id } = useParams();

  const sections = [
    { key: "documents", to: `/properties/${id}/documents` },
    { key: "announcements", to: `/properties/${id}/announcements` },
    { key: "assemblies", to: `/properties/${id}/assemblies` },
    { key: "account", to: `/properties/${id}/account` },
    { key: "vendors", to: `/properties/${id}/vendors` },
    { key: "details", to: `/properties/${id}/details` },
  ];

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h6" gutterBottom>
          {t("properties.start.title")}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t("properties.start.subtitle")}
        </Typography>
      </Box>

      <Button
        variant="contained"
        size="large"
        startIcon={<AddIcon />}
        onClick={() => navigate("/tickets/new")}
        sx={{ alignSelf: "flex-start" }}
      >
        {t("tickets.newButton")}
      </Button>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", md: "repeat(3, 1fr)" },
          gap: 2,
        }}
      >
        {sections.map((s) => (
          <Card key={s.key} variant="outlined">
            <CardActionArea
              sx={{ p: 2, height: "100%" }}
              onClick={() => navigate(s.to)}
            >
              <Typography sx={{ fontWeight: 600 }}>
                {t(`properties.tabs.${s.key}`)}
              </Typography>
            </CardActionArea>
          </Card>
        ))}
      </Box>
    </Stack>
  );
}
