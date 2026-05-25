import { Link as RouterLink, useParams } from "react-router-dom";
import { Box, Link, Stack, Typography } from "@mui/material";
import { useTranslation } from "react-i18next";
import { DocumentFoldersPanel } from "@/components/DocumentFoldersPanel";

/** Portal-side documents browser.
 *
 *  Item 6: the Verwalter organises documents into a folder tree per
 *  property; Eigentümer / Mieter / Beirat see that same tree here in
 *  read-only mode. DocumentFoldersPanel does the heavy lifting — this
 *  page is just the header chrome + scope check (the panel itself
 *  hits /me/* endpoints which 404 on properties the caller can't see).
 */
export function PropertyDocumentsPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();

  if (!id) return null;

  return (
    <Stack spacing={4}>
      <Box>
        <Link
          component={RouterLink}
          to={`/properties/${id}`}
          color="text.secondary"
          underline="hover"
        >
          ← {t("properties.title")}
        </Link>
      </Box>

      <Box>
        <Typography variant="h4" component="h1" sx={{ fontWeight: 700 }}>
          {t("documents.rootCrumb")}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          {t("documents.portalIntro")}
        </Typography>
      </Box>

      <DocumentFoldersPanel propertyId={id} mode="portal" />
    </Stack>
  );
}
