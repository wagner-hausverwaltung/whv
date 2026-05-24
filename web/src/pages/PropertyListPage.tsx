import { useEffect, useState } from "react";
import { Link as RouterLink, Navigate } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Link,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type { PropertyResponse } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";

export function PropertyListPage() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [properties, setProperties] = useState<PropertyResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<PropertyResponse[]>("/me/properties")
      .then((r) => setProperties(r.data))
      .catch(() => setError(t("properties.loadFailed")));
  }, [t]);

  if (error) return <Alert severity="error">{error}</Alert>;
  if (properties === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t("common.loading")}
      </Typography>
    );
  }

  const isVerwalter = user?.role === "verwalter";
  const isUnbound = user && !isVerwalter && user.contact_id_impower === null;

  // Single-property users skip the list entirely — jump straight to detail.
  // The header already shows the active property's address (Layout reads
  // /me/properties and matches the route), so a "list of one" page would be
  // dead weight.
  if (properties.length === 1 && !isVerwalter) {
    const only = properties[0]!;
    return <Navigate to={`/properties/${only.id}`} replace />;
  }

  // "New ticket" CTA is the most common action on the home screen — give it
  // the full content width so it's the visual anchor regardless of how many
  // properties are listed below.
  const ticketCta = (
    <Button
      component={RouterLink}
      to="/tickets/new"
      variant="contained"
      size="large"
      fullWidth
      startIcon={<AddIcon />}
    >
      {t("tickets.newButton")}
    </Button>
  );

  if (properties.length === 0) {
    return (
      <Stack spacing={3}>
        <Typography variant="body2" color="text.secondary">
          {isUnbound ? t("properties.unbound") : t("properties.empty")}
        </Typography>
        {ticketCta}
      </Stack>
    );
  }

  return (
    <Stack spacing={3}>
      {ticketCta}

      {isVerwalter && (
        <Alert severity="info" variant="outlined">
          {t("properties.verwalterNote")}{" "}
          <Link component={RouterLink} to="/admin" underline="hover">
            {t("properties.adminLink")}
          </Link>
        </Alert>
      )}

      {/* Minimal list of just-the-name; the address shows on hover/in-detail. */}
      <Box
        sx={{
          bgcolor: "background.paper",
          border: 1,
          borderColor: "divider",
          borderRadius: 1,
        }}
      >
        <List disablePadding>
          {properties.map((p, i) => (
            <ListItem
              key={p.id}
              disablePadding
              divider={i < properties.length - 1}
              secondaryAction={
                p.property_hr_id && (
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{
                      fontFamily: "ui-monospace, Menlo, monospace",
                      pr: 1,
                    }}
                  >
                    {p.property_hr_id}
                  </Typography>
                )
              }
            >
              <ListItemButton component={RouterLink} to={`/properties/${p.id}`}>
                <ListItemText
                  primary={
                    <Typography variant="body1" sx={{ fontWeight: 500 }}>
                      {p.name}
                    </Typography>
                  }
                  secondary={
                    [
                      p.street && [p.street, p.number].filter(Boolean).join(" "),
                      [p.postal_code, p.city].filter(Boolean).join(" "),
                    ]
                      .filter(Boolean)
                      .join(" · ") || null
                  }
                />
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      </Box>
    </Stack>
  );
}
