import Avatar, { type AvatarProps } from "@mui/material/Avatar";
import { useAuthedImageUrl } from "@/lib/useAuthedImageUrl";

type AuthedAvatarProps = Omit<AvatarProps, "src"> & {
  relativeUrl: string | null | undefined;
};

/**
 * MUI Avatar whose image is loaded through the authenticated
 * `/admin/property-images` endpoint (browsers won't attach the JWT to a
 * plain `<img src>`). Shows its children (typically a fallback icon)
 * until/unless the image loads.
 */
export function AuthedAvatar({
  relativeUrl,
  children,
  ...rest
}: AuthedAvatarProps) {
  const src = useAuthedImageUrl(relativeUrl);
  return (
    <Avatar src={src} {...rest}>
      {children}
    </Avatar>
  );
}
