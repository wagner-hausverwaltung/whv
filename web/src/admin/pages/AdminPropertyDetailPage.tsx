import { useCallback, useEffect, useState, type SyntheticEvent } from "react";
import {
  Link as RouterLink,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  Alert,
  Box,
  Link,
  Paper,
  Stack,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tabs,
  Typography,
} from "@mui/material";
import { useTranslation } from "react-i18next";
import { api } from "@/api/client";
import type {
  AdminPropertyCompanyResponse,
  AdminPropertyDetailResponse,
} from "@/api/types";
import { AdminTicketsPage } from "./AdminTicketsPage";

type TabKey = "overview" | "tickets" | "companies";

function OverviewTab({ p }: { p: AdminPropertyDetailResponse }) {
  const { t } = useTranslation();
  const street = [p.street, p.number].filter(Boolean).join(" ");
  const zipCity = [p.postal_code, p.city].filter(Boolean).join(" ");
  const address = [street, zipCity].filter(Boolean).join(" · ") || "—";

  const rows: { label: string; value: string | number }[] = [
    { label: t("admin.propertyDetail.address"), value: address },
    { label: t("admin.propertyDetail.type"), value: p.type },
    { label: t("admin.propertyDetail.state"), value: p.state },
    { label: t("admin.propertyDetail.hrId"), value: p.property_hr_id ?? "—" },
    { label: t("admin.propertyDetail.impowerId"), value: p.impower_id ?? "—" },
  ];

  return (
    <Stack spacing={3}>
      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.label}>
                <TableCell
                  sx={{
                    width: "30%",
                    color: "text.secondary",
                    fontSize: "0.85rem",
                  }}
                >
                  {row.label}
                </TableCell>
                <TableCell>{row.value}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr 1fr",
            sm: "repeat(3, 1fr)",
            md: "repeat(6, 1fr)",
          },
          gap: 2,
        }}
      >
        {(
          [
            ["units_count", "units"],
            ["contracts_count", "contracts"],
            ["contacts_count", "contacts"],
            ["open_tickets_count", "openTickets"],
            ["open_resolutions_count", "openResolutions"],
            ["invoice_companies_count", "invoiceCompanies"],
          ] as const
        ).map(([field, label]) => (
          <Paper
            key={field}
            variant="outlined"
            sx={{ p: 2, textAlign: "center" }}
          >
            <Typography
              variant="h4"
              sx={{ fontWeight: 700, lineHeight: 1, mb: 0.5 }}
            >
              {p[field]}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {t(`admin.propertyDetail.${label}`)}
            </Typography>
          </Paper>
        ))}
      </Box>
    </Stack>
  );
}

function CompaniesTab({ propertyId }: { propertyId: string }) {
  const { t } = useTranslation();
  const [rows, setRows] = useState<AdminPropertyCompanyResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    setRows(null);
    try {
      const r = await api.get<AdminPropertyCompanyResponse[]>(
        `/admin/properties/${propertyId}/companies`,
      );
      setRows(r.data);
    } catch {
      setError(t("admin.propertyDetail.loadFailed"));
    }
  }, [propertyId, t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  if (error) return <Alert severity="error">{error}</Alert>;
  if (rows === null) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t("common.loading")}
      </Typography>
    );
  }
  if (rows.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t("admin.propertyDetail.noCompanies")}
      </Typography>
    );
  }

  return (
    <Stack spacing={2}>
      <Typography variant="body2" color="text.secondary">
        {t("admin.propertyDetail.companiesIntro")}
      </Typography>
      <TableContainer component={Paper} variant="outlined">
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t("admin.propertyDetail.companyName")}</TableCell>
              <TableCell>{t("admin.propertyDetail.invoices")}</TableCell>
              <TableCell align="right">
                {t("admin.propertyDetail.totalAmount")}
              </TableCell>
              <TableCell>{t("admin.propertyDetail.lastInvoice")}</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.contact_id} hover>
                <TableCell>
                  <Stack spacing={0}>
                    <Typography variant="body2" sx={{ fontWeight: 500 }}>
                      {r.name}
                    </Typography>
                    {(r.email || r.phone) && (
                      <Typography variant="caption" color="text.secondary">
                        {[r.email, r.phone].filter(Boolean).join(" · ")}
                      </Typography>
                    )}
                  </Stack>
                </TableCell>
                <TableCell>{r.invoice_count}</TableCell>
                <TableCell align="right">
                  {r.total_amount != null
                    ? r.total_amount.toLocaleString("de-DE", {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })
                    : "—"}
                </TableCell>
                <TableCell>
                  <Typography variant="caption" color="text.secondary">
                    {r.most_recent_invoice_at
                      ? new Date(r.most_recent_invoice_at).toLocaleDateString(
                          "de-DE",
                        )
                      : "—"}
                  </Typography>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Stack>
  );
}

export function AdminPropertyDetailPage() {
  const { t } = useTranslation();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const activeTab = (params.get("tab") ?? "overview") as TabKey;
  const [detail, setDetail] = useState<AdminPropertyDetailResponse | null>(
    null,
  );
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    api
      .get<AdminPropertyDetailResponse>(`/admin/properties/${id}`)
      .then((r) => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        if (!cancelled) setDetail(r.data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const status = (err as { response?: { status?: number } }).response
          ?.status;
        if (status === 404) setNotFound(true);
        else setError(t("admin.propertyDetail.loadFailed"));
      });
    return () => {
      cancelled = true;
    };
  }, [id, t]);

  const onTabChange = (_: SyntheticEvent, next: TabKey) => {
    const p = new URLSearchParams(params);
    if (next === "overview") p.delete("tab");
    else p.set("tab", next);
    setParams(p);
  };

  if (notFound) {
    return (
      <Stack spacing={2}>
        <Alert severity="error">{t("admin.propertyDetail.notFound")}</Alert>
        <Link
          component="button"
          onClick={() => navigate("/admin/properties")}
          underline="hover"
        >
          {t("admin.propertyDetail.back")}
        </Link>
      </Stack>
    );
  }
  if (detail === null) {
    if (error) return <Alert severity="error">{error}</Alert>;
    return (
      <Typography variant="body2" color="text.secondary">
        {t("common.loading")}
      </Typography>
    );
  }

  const street = [detail.street, detail.number].filter(Boolean).join(" ");
  const zipCity = [detail.postal_code, detail.city].filter(Boolean).join(" ");
  const subtitleParts = [street, zipCity].filter(Boolean);

  return (
    <Stack spacing={3}>
      <Box>
        <Link
          component={RouterLink}
          to="/admin/properties"
          color="text.secondary"
        >
          {t("admin.propertyDetail.back")}
        </Link>
      </Box>

      <Box>
        <Typography variant="h4" component="h1" gutterBottom>
          {detail.name}
        </Typography>
        {subtitleParts.length > 0 && (
          <Typography variant="body2" color="text.secondary">
            {subtitleParts.join(" · ")}
          </Typography>
        )}
      </Box>

      <Tabs
        value={activeTab}
        onChange={onTabChange}
        sx={{ borderBottom: 1, borderColor: "divider" }}
      >
        <Tab value="overview" label={t("admin.propertyDetail.tabOverview")} />
        <Tab
          value="tickets"
          label={`${t("admin.propertyDetail.tabTickets")} (${detail.open_tickets_count})`}
        />
        <Tab
          value="companies"
          label={`${t("admin.propertyDetail.tabCompanies")} (${detail.invoice_companies_count})`}
        />
      </Tabs>

      {activeTab === "overview" && <OverviewTab p={detail} />}
      {activeTab === "tickets" && id && (
        <AdminTicketsPage filterPropertyId={id} showHeader={false} />
      )}
      {activeTab === "companies" && id && <CompaniesTab propertyId={id} />}
    </Stack>
  );
}
