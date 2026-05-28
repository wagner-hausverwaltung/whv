/**
 * AppBar property-switcher: shows the active address as a clickable
 * button; on click opens a Menu of the user's other properties.
 *
 * When the user has only one property, the chevron + menu are
 * suppressed and the button renders as a non-interactive identity
 * label (still clickable so it can act as a "home" link, but no menu
 * opens).
 *
 * Switching properties preserves the active tab segment in the URL
 * — if the user was on /properties/A/announcements and picks
 * property B, we land on /properties/B/announcements rather than
 * resetting to "details". Same trick as the iOS app where switching
 * Liegenschaften keeps you on the same tab.
 */

import { useEffect, useMemo, useState, type MouseEvent } from "react";
import {
  matchPath,
  useLocation,
  useNavigate,
} from "react-router-dom";
import {
  Avatar,
  Box,
  ButtonBase,
  Divider,
  Menu,
  MenuItem,
  Stack,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import HomeWorkOutlinedIcon from "@mui/icons-material/HomeWorkOutlined";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import CheckIcon from "@mui/icons-material/Check";
import { api, API_BASE_URL } from "@/api/client";
import type { PropertyResponse } from "@/api/types";

function formatAddress(p: PropertyResponse): string | null {
  const street = [p.street, p.number].filter(Boolean).join(" ");
  const zip = [p.postal_code, p.city].filter(Boolean).join(" ");
  const combined = [street, zip].filter(Boolean).join(" · ");
  return combined || null;
}

/// "Is the formatted address already implied by the property name?"
/// Wagner's naming convention always bakes the address into the name
/// ("MV Hahnstraße 33, 70199 Stuttgart"), so rendering the address
/// as a subtitle is pure duplication. We compare normalised tokens
/// — strip type prefix, punctuation, casing — and suppress the
/// subtitle when both the street tokens AND the city token are in
/// the name. Properties named differently (legacy / demo) keep the
/// subtitle.
function addressRedundantWith(name: string, p: PropertyResponse): boolean {
  if (!p.street || !p.city) return false;
  // Normalise so the abbreviated form in the name ("Schmidener Str.")
  // and the spelled-out form in the address field ("Schmidener
  // Straße") tokenise to the same thing. ß→ss, then collapse the
  // common street suffixes (straße/strasse/str) to a single token.
  const tokens = (s: string) =>
    s
      .toLowerCase()
      .replace(/ß/g, "ss")
      .replace(/[.,·]/g, " ")
      .split(/\s+/)
      .filter(Boolean)
      .map((t) => t.replace(/strasse/g, "str"));
  const nameTokens = new Set(tokens(name));
  const streetTokens = tokens(p.street);
  const cityToken = tokens(p.city)[0];
  const allStreetIn = streetTokens.every((t) => nameTokens.has(t));
  const cityIn = cityToken ? nameTokens.has(cityToken) : true;
  return allStreetIn && cityIn;
}

// Tab segment the user is currently on, so the switcher can preserve
// it across properties. Anything we don't recognise (e.g. the user is
// on /tickets, not in a property) returns null and the switcher
// defaults to "details".
function currentTabSegment(pathname: string): string | null {
  const m = matchPath("/properties/:id/:tab", pathname);
  return (m?.params.tab as string | undefined) ?? null;
}

export function PropertySwitcher() {
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useTheme();
  const isWide = useMediaQuery(theme.breakpoints.up("sm"));

  const [properties, setProperties] = useState<PropertyResponse[] | null>(null);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .get<PropertyResponse[]>("/me/properties")
      .then((r) => {
        if (!cancelled) setProperties(r.data);
      })
      .catch(() => {
        if (!cancelled) setProperties([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const activeId = useMemo(() => {
    const m = matchPath("/properties/:id/*", location.pathname);
    return (m?.params.id as string | undefined) ?? null;
  }, [location.pathname]);

  const active: PropertyResponse | null = useMemo(() => {
    if (!properties || properties.length === 0) return null;
    if (activeId) {
      return properties.find((p) => p.id === activeId) ?? properties[0]!;
    }
    return properties[0] ?? null;
  }, [properties, activeId]);

  const hasMultiple = (properties?.length ?? 0) > 1;

  const openMenu = (e: MouseEvent<HTMLElement>) => {
    if (!hasMultiple) return;
    setAnchor(e.currentTarget);
  };
  const closeMenu = () => setAnchor(null);

  const pick = (p: PropertyResponse) => {
    closeMenu();
    const tab = currentTabSegment(location.pathname) ?? "details";
    navigate(`/properties/${p.id}/${tab}`);
  };

  // Loading / nothing-to-show state: don't reserve any space so the
  // AppBar doesn't reflow once the data arrives.
  if (!active) return null;

  const address = formatAddress(active);
  const showActiveAddress =
    !!address && !addressRedundantWith(active.name, active);

  return (
    <>
      <ButtonBase
        onClick={openMenu}
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1,
          borderRadius: 1,
          px: 1,
          py: 0.5,
          textAlign: "left",
          color: "inherit",
          "&:hover": {
            bgcolor: hasMultiple ? "action.hover" : "transparent",
          },
        }}
        aria-haspopup={hasMultiple ? "menu" : undefined}
        aria-expanded={hasMultiple && Boolean(anchor) ? "true" : undefined}
        disableRipple={!hasMultiple}
      >
        <Avatar
          src={
            active.image_url ? `${API_BASE_URL}${active.image_url}` : undefined
          }
          sx={{
            width: 32,
            height: 32,
            bgcolor: "action.hover",
            color: "text.disabled",
          }}
        >
          <HomeWorkOutlinedIcon sx={{ fontSize: 18 }} />
        </Avatar>
        <Stack spacing={0} sx={{ lineHeight: 1.2, minWidth: 0 }}>
          {active.name && isWide && (
            <Typography
              variant="body2"
              sx={{ fontWeight: 600 }}
              noWrap
            >
              {active.name}
            </Typography>
          )}
          {showActiveAddress && (
            <Typography variant="caption" color="text.secondary" noWrap>
              {address}
            </Typography>
          )}
        </Stack>
        {hasMultiple && (
          <KeyboardArrowDownIcon
            fontSize="small"
            sx={{ color: "text.secondary", flexShrink: 0 }}
          />
        )}
      </ButtonBase>

      {hasMultiple && properties && (
        <Menu
          anchorEl={anchor}
          open={Boolean(anchor)}
          onClose={closeMenu}
          slotProps={{ paper: { sx: { minWidth: 280 } } }}
        >
          <MenuItem disabled sx={{ opacity: "1 !important" }}>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ textTransform: "uppercase", letterSpacing: 0.5 }}
            >
              Liegenschaft wechseln
            </Typography>
          </MenuItem>
          <Divider />
          {properties.map((p) => {
            const addr = formatAddress(p);
            const showAddr = !!addr && !addressRedundantWith(p.name, p);
            const isActive = p.id === active.id;
            return (
              <MenuItem
                key={p.id}
                onClick={() => pick(p)}
                selected={isActive}
              >
                <Avatar
                  src={p.image_url ? `${API_BASE_URL}${p.image_url}` : undefined}
                  sx={{
                    width: 28,
                    height: 28,
                    mr: 1.5,
                    bgcolor: "action.hover",
                    color: "text.disabled",
                  }}
                >
                  <HomeWorkOutlinedIcon sx={{ fontSize: 16 }} />
                </Avatar>
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography variant="body2" sx={{ fontWeight: 500 }} noWrap>
                    {p.name}
                  </Typography>
                  {showAddr && (
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      noWrap
                    >
                      {addr}
                    </Typography>
                  )}
                </Box>
                {isActive && (
                  <CheckIcon
                    fontSize="small"
                    sx={{ ml: 1, color: "primary.main" }}
                  />
                )}
              </MenuItem>
            );
          })}
        </Menu>
      )}
    </>
  );
}
