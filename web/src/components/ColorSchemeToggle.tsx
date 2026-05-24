import { useState, type MouseEvent } from "react";
import {
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Tooltip,
} from "@mui/material";
import LightModeIcon from "@mui/icons-material/LightMode";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import SettingsBrightnessIcon from "@mui/icons-material/SettingsBrightness";
import { useTranslation } from "react-i18next";
import { useColorScheme } from "@/theme/colorScheme";

export function ColorSchemeToggle() {
  const { scheme, setScheme, resolved } = useColorScheme();
  const { t } = useTranslation();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  const open = (e: MouseEvent<HTMLElement>) => setAnchor(e.currentTarget);
  const close = () => setAnchor(null);

  const Icon =
    scheme === "system"
      ? SettingsBrightnessIcon
      : resolved === "dark"
        ? DarkModeIcon
        : LightModeIcon;

  return (
    <>
      <Tooltip title={t("common.appearance")}>
        <IconButton
          onClick={open}
          color="inherit"
          aria-label={t("common.appearance")}
          size="small"
        >
          <Icon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={close}>
        <MenuItem
          onClick={() => {
            setScheme("light");
            close();
          }}
          selected={scheme === "light"}
        >
          <ListItemIcon>
            <LightModeIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t("common.appearanceLight")}</ListItemText>
        </MenuItem>
        <MenuItem
          onClick={() => {
            setScheme("dark");
            close();
          }}
          selected={scheme === "dark"}
        >
          <ListItemIcon>
            <DarkModeIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t("common.appearanceDark")}</ListItemText>
        </MenuItem>
        <MenuItem
          onClick={() => {
            setScheme("system");
            close();
          }}
          selected={scheme === "system"}
        >
          <ListItemIcon>
            <SettingsBrightnessIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText>{t("common.appearanceSystem")}</ListItemText>
        </MenuItem>
      </Menu>
    </>
  );
}
