import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Box, Stack, Typography } from "@mui/material";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type { PropertyDetailResponse } from "@/api/types";
import { DocumentFoldersPanel } from "@/components/DocumentFoldersPanel";

/** Portal-side documents browser.
 *
 *  Item 6: the Verwalter organises documents into a folder tree per
 *  property; Eigentümer / Mieter / Beirat see that same tree here in
 *  read-only mode. DocumentFoldersPanel does the heavy lifting — this
 *  tab is just a brief intro + the panel. The workspace tab above
 *  carries navigation, so no breadcrumb / page title here.
 *
 *  We do one cheap fetch of `/me/properties/{id}` to grab the units
 *  the caller can see — so row-scope chips on unit-pinned docs can
 *  show "Einheit W01" instead of the generic fallback. The fetch is
 *  best-effort; if it fails, the panel still works.
 */
export function PropertyDocumentsPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const [units, setUnits] = useState<
    { id: string; unit_hr_id: string | null }[] | undefined
  >(undefined);

  useEffect(() => {
    if (!id) return;
    api
      .get<PropertyDetailResponse>(`/me/properties/${id}`)
      .then((r) =>
        setUnits(
          r.data.units.map((u) => ({ id: u.id, unit_hr_id: u.unit_hr_id })),
        ),
      )
      .catch(() => {
        // Best-effort: panel falls back to the generic "Einheit" chip.
      });
  }, [id]);

  if (!id) return null;

  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="body2" color="text.secondary">
          {t("documents.portalIntro")}
        </Typography>
      </Box>
      <DocumentFoldersPanel propertyId={id} mode="portal" units={units} />
    </Stack>
  );
}
