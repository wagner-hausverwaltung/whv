import { useEffect, useState } from "react";
import { api } from "@/api/client";

/**
 * Auth-gated images (e.g. property hero photos served by the authenticated
 * `/admin/property-images/{file}` endpoint) can't be loaded via a plain
 * `<img src>` or CSS `url()` — the browser never attaches the JWT to those
 * requests. This hook fetches the bytes through the authed api client (which
 * carries the token and refreshes on 401) and returns an object URL,
 * revoking it on unmount / url change. Returns `undefined` until loaded.
 */
export function useAuthedImageUrl(
  relativeUrl: string | null | undefined,
): string | undefined {
  const [objectUrl, setObjectUrl] = useState<string | undefined>(undefined);
  useEffect(() => {
    if (!relativeUrl) return;
    let active = true;
    let created: string | undefined;
    api
      .get<Blob>(relativeUrl, { responseType: "blob" })
      .then((res) => {
        if (!active) return;
        created = URL.createObjectURL(res.data);
        setObjectUrl(created);
      })
      .catch(() => {
        if (active) setObjectUrl(undefined);
      });
    return () => {
      active = false;
      setObjectUrl(undefined);
      if (created) URL.revokeObjectURL(created);
    };
  }, [relativeUrl]);
  return objectUrl;
}
