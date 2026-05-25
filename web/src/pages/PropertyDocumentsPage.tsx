import { useParams } from "react-router-dom";
import { Box, Stack, Typography } from "@mui/material";
import { useTranslation } from "react-i18next";
import { DocumentFoldersPanel } from "@/components/DocumentFoldersPanel";

/** Portal-side documents browser.
 *
 *  Item 6: the Verwalter organises documents into a folder tree per
 *  property; Eigentümer / Mieter / Beirat see that same tree here in
 *  read-only mode. DocumentFoldersPanel does the heavy lifting — this
 *  tab is just a brief intro + the panel. The workspace tab above
 *  carries navigation, so no breadcrumb / page title here.
 */
export function PropertyDocumentsPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();

  if (!id) return null;

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="body2" color="text.secondary">
          {t("documents.portalIntro")}
        </Typography>
      </Box>
      <DocumentFoldersPanel propertyId={id} mode="portal" />
    </Stack>
  );
}
