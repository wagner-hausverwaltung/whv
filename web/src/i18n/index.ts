import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";
import de from "./locales/de.json";
import en from "./locales/en.json";

// Browser-default language with localStorage override. The detector inspects
// localStorage first (key `i18nextLng`), then navigator.language. We support
// `de` and `en` only — anything else falls back to `de` (the customer's
// primary market).
void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      de: { translation: de },
      en: { translation: en },
    },
    fallbackLng: "de",
    supportedLngs: ["de", "en"],
    nonExplicitSupportedLngs: true, // treat 'en-US', 'de-AT', etc. as 'en'/'de'
    interpolation: { escapeValue: false }, // React already escapes
    detection: {
      order: ["localStorage", "navigator", "htmlTag"],
      lookupLocalStorage: "i18nextLng",
      caches: ["localStorage"],
    },
  });

export default i18n;

export const LANGUAGES = [
  { code: "de", label: "Deutsch", flag: "🇩🇪" },
  { code: "en", label: "English", flag: "🇬🇧" },
] as const;

export type LangCode = (typeof LANGUAGES)[number]["code"];
