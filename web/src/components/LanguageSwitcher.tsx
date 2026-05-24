import { useState, type MouseEvent } from "react";
import {
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Tooltip,
} from "@mui/material";
import LanguageIcon from "@mui/icons-material/Language";
import { useTranslation } from "react-i18next";
import { LANGUAGES, type LangCode } from "@/i18n";

export function LanguageSwitcher() {
  const { i18n, t } = useTranslation();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  const current = LANGUAGES.find((l) => l.code === i18n.resolvedLanguage) ??
    LANGUAGES[0];

  const open = (e: MouseEvent<HTMLElement>) => setAnchor(e.currentTarget);
  const close = () => setAnchor(null);
  const pick = (code: LangCode) => {
    void i18n.changeLanguage(code);
    close();
  };

  return (
    <>
      <Tooltip title={t("common.language")}>
        <IconButton
          onClick={open}
          color="inherit"
          aria-label={t("common.language")}
          size="small"
        >
          <span style={{ fontSize: "1.25rem", lineHeight: 1 }}>
            {current.flag}
          </span>
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={close}>
        {LANGUAGES.map((l) => (
          <MenuItem
            key={l.code}
            onClick={() => pick(l.code)}
            selected={l.code === current.code}
          >
            <ListItemIcon>
              <span style={{ fontSize: "1.25rem" }}>{l.flag}</span>
            </ListItemIcon>
            <ListItemText>{l.label}</ListItemText>
          </MenuItem>
        ))}
        <MenuItem divider disabled sx={{ fontSize: "0.75rem" }}>
          <LanguageIcon fontSize="small" sx={{ mr: 1 }} />
          {t("common.language")}
        </MenuItem>
      </Menu>
    </>
  );
}
