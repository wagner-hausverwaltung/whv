// Built-in signature canvas (no external dependency). Draws black strokes
// on a transparent canvas via pointer events (mouse + touch), and exports a
// PNG Blob the caller uploads. The backend composites that PNG onto the
// Vollmacht PDF (ADR-0017).

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
} from "react";
import { Box, Button, Stack, Typography } from "@mui/material";
import { useTranslation } from "react-i18next";

export interface SignaturePadHandle {
  /** PNG of the drawn signature, or null if nothing was drawn. */
  toBlob: () => Promise<Blob | null>;
  isEmpty: () => boolean;
  clear: () => void;
}

interface SignaturePadProps {
  height?: number;
  label?: string;
}

export const SignaturePad = forwardRef<SignaturePadHandle, SignaturePadProps>(
  function SignaturePad({ height = 160, label }, ref) {
    const { t } = useTranslation();
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const drawing = useRef(false);
    const dirty = useRef(false);
    const last = useRef<{ x: number; y: number } | null>(null);

    // Size the bitmap to the element's CSS size × devicePixelRatio so strokes
    // stay crisp; reset on mount + when the container resizes.
    useEffect(() => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const resize = () => {
        const rect = canvas.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.max(1, Math.round(rect.width * dpr));
        canvas.height = Math.max(1, Math.round(rect.height * dpr));
        const ctx = canvas.getContext("2d");
        if (ctx) {
          ctx.scale(dpr, dpr);
          ctx.lineWidth = 2.5;
          ctx.lineCap = "round";
          ctx.lineJoin = "round";
          ctx.strokeStyle = "#111111";
        }
        dirty.current = false;
      };
      resize();
      window.addEventListener("resize", resize);
      return () => window.removeEventListener("resize", resize);
    }, []);

    const pos = (e: React.PointerEvent<HTMLCanvasElement>) => {
      const rect = e.currentTarget.getBoundingClientRect();
      return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    };

    const down = (e: React.PointerEvent<HTMLCanvasElement>) => {
      e.currentTarget.setPointerCapture(e.pointerId);
      drawing.current = true;
      last.current = pos(e);
    };

    const move = (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (!drawing.current) return;
      const ctx = canvasRef.current?.getContext("2d");
      const p = pos(e);
      if (ctx && last.current) {
        ctx.beginPath();
        ctx.moveTo(last.current.x, last.current.y);
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
        dirty.current = true;
      }
      last.current = p;
    };

    const up = () => {
      drawing.current = false;
      last.current = null;
    };

    const clear = useCallback(() => {
      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");
      if (canvas && ctx) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        dirty.current = false;
      }
    }, []);

    useImperativeHandle(
      ref,
      () => ({
        isEmpty: () => !dirty.current,
        clear,
        toBlob: () =>
          new Promise((resolve) => {
            const canvas = canvasRef.current;
            if (!canvas || !dirty.current) {
              resolve(null);
              return;
            }
            canvas.toBlob((b) => resolve(b), "image/png");
          }),
      }),
      [clear],
    );

    return (
      <Stack spacing={0.5}>
        <Box
          sx={{
            border: 1,
            borderColor: "divider",
            borderRadius: 1,
            bgcolor: "background.paper",
            touchAction: "none", // let the canvas own touch gestures
          }}
        >
          <canvas
            ref={canvasRef}
            style={{ width: "100%", height, display: "block", cursor: "crosshair" }}
            onPointerDown={down}
            onPointerMove={move}
            onPointerUp={up}
            onPointerLeave={up}
          />
        </Box>
        <Stack direction="row" sx={{ alignItems: "center", justifyContent: "space-between" }}>
          <Typography variant="caption" color="text.secondary">
            {label ?? t("signature.here")}
          </Typography>
          <Button size="small" onClick={clear}>
            {t("signature.clear")}
          </Button>
        </Stack>
      </Stack>
    );
  },
);
