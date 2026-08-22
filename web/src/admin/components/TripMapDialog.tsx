// Routes on a map — one trip or a whole month. OpenStreetMap tiles via
// Leaflet; the phone ships Google-encoded polylines, decoded client-side
// (lib/trips.ts). Start = green dot, end = red dot, route = the WHV blue.
// Trips without a stored route (driver switched "Route speichern" off)
// still show as start/end dots when coordinates exist.

import { useMemo } from "react";
import { Dialog, DialogContent, DialogTitle, IconButton, Typography } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from "react-leaflet";
import type { LatLngBoundsExpression, LatLngExpression } from "leaflet";
import "leaflet/dist/leaflet.css";
import type { TripResponse } from "@/api/types";
import { decodePolyline, purposeLabel } from "@/lib/trips";

interface Props {
  title: string;
  trips: TripResponse[];
  onClose: () => void;
}

function num(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

export function TripMapDialog({ title, trips, onClose }: Props) {
  const shapes = useMemo(
    () =>
      trips.map((t) => {
        const route = t.route_polyline ? decodePolyline(t.route_polyline) : [];
        const sLat = num(t.start_lat), sLng = num(t.start_lng);
        const eLat = num(t.end_lat), eLng = num(t.end_lng);
        return {
          trip: t,
          route,
          start: sLat !== null && sLng !== null ? ([sLat, sLng] as LatLngExpression) : null,
          end: eLat !== null && eLng !== null ? ([eLat, eLng] as LatLngExpression) : null,
        };
      }),
    [trips],
  );

  const bounds = useMemo<LatLngBoundsExpression | null>(() => {
    const pts: [number, number][] = [];
    for (const s of shapes) {
      for (const p of s.route) pts.push(p);
      if (s.start) pts.push(s.start as [number, number]);
      if (s.end) pts.push(s.end as [number, number]);
    }
    if (pts.length === 0) return null;
    let minLat = Infinity, minLng = Infinity, maxLat = -Infinity, maxLng = -Infinity;
    for (const [la, ln] of pts) {
      minLat = Math.min(minLat, la); maxLat = Math.max(maxLat, la);
      minLng = Math.min(minLng, ln); maxLng = Math.max(maxLng, ln);
    }
    // A single point would give a degenerate box — pad it.
    if (minLat === maxLat && minLng === maxLng) {
      return [[minLat - 0.01, minLng - 0.01], [maxLat + 0.01, maxLng + 0.01]];
    }
    return [[minLat, minLng], [maxLat, maxLng]];
  }, [shapes]);

  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: "flex", alignItems: "center", pr: 1 }}>
        <span style={{ flex: 1 }}>{title}</span>
        <IconButton onClick={onClose} aria-label="Schließen" size="small"><CloseIcon /></IconButton>
      </DialogTitle>
      <DialogContent sx={{ p: 0, height: 520 }}>
        {bounds ? (
          <MapContainer bounds={bounds} boundsOptions={{ padding: [24, 24] }} style={{ height: "100%", width: "100%" }} scrollWheelZoom>
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
              url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            {shapes.map(({ trip, route, start, end }) => (
              <span key={trip.id}>
                {route.length > 1 && (
                  <Polyline positions={route} pathOptions={{ color: "#1e5aa8", weight: 4, opacity: 0.85 }}>
                    <Tooltip sticky>
                      {new Date(trip.started_at).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "short" })}
                      {" · "}{trip.property_name ?? purposeLabel(trip.purpose)}
                      {" · "}{((trip.distance_m ?? 0) / 1000).toLocaleString("de-DE", { maximumFractionDigits: 1 })} km
                    </Tooltip>
                  </Polyline>
                )}
                {start && <CircleMarker center={start} radius={5} pathOptions={{ color: "#2e7d32", fillColor: "#2e7d32", fillOpacity: 1 }} />}
                {end && <CircleMarker center={end} radius={5} pathOptions={{ color: "#c62828", fillColor: "#c62828", fillOpacity: 1 }} />}
              </span>
            ))}
          </MapContainer>
        ) : (
          <Typography variant="body2" color="text.secondary" sx={{ p: 3 }}>
            Keine Positionsdaten für diese Fahrten.
          </Typography>
        )}
      </DialogContent>
    </Dialog>
  );
}
