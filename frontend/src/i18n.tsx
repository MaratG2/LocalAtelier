import { useSyncExternalStore } from "react";
import { Languages } from "lucide-react";
import russian from "./ru.json";

export type Language = "en" | "ru";
const dictionary: Record<string, string> = russian;
const listeners = new Set<() => void>();
const initialLanguage = (): Language => {
  try {
    const saved = localStorage.getItem("atelier.language.v1");
    if (saved === "en" || saved === "ru") return saved;
  } catch {
    /* Storage may be disabled. */
  }
  return navigator.language.startsWith("ru") ? "ru" : "en";
};
let language = initialLanguage();
document.documentElement.lang = language;
export const locale = () => (language === "ru" ? "ru-RU" : "en-US");
export const number = (value: number, digits = 1) =>
  value.toLocaleString(locale(), { maximumFractionDigits: digits });
export function quantity(value: number, kind: "seconds" | "references") {
  if (language === "en")
    return `${value} ${value === 1 ? kind.slice(0, -1) : kind}`;
  const form = new Intl.PluralRules(locale()).select(value);
  const words =
    kind === "seconds"
      ? ["секунда", "секунды", "секунд"]
      : ["референс", "референса", "референсов"];
  return `${number(value)} ${words[form === "one" ? 0 : form === "few" ? 1 : 2]}`;
}
export function setLanguage(next: Language) {
  language = next;
  document.documentElement.lang = next;
  try {
    localStorage.setItem("atelier.language.v1", next);
  } catch {
    /* In-memory preference still works. */
  }
  listeners.forEach((listener) => listener());
}
export function useLanguage() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    () => language,
  );
}
const patterns = Object.entries(dictionary)
  .filter(([key]) => /\{\d+\}/.test(key))
  .map(([key, value]) => ({
    regex: new RegExp(
      "^" +
        key
          .split(/\{\d+\}/)
          .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
          .join("(.*?)") +
        "$",
    ),
    value,
  }));
export function t(
  value: string | undefined | null,
  ...args: unknown[]
): string {
  if (value == null) return "";
  let result = value;
  if (language === "ru") {
    result = dictionary[value] ?? dictionary[value.trim()] ?? value;
    if (result === value) {
      for (const pattern of patterns) {
        const match = value.match(pattern.regex);
        if (match) {
          result = pattern.value.replace(
            /\{(\d+)\}/g,
            (_, i) => match[Number(i) + 1] || "",
          );
          break;
        }
      }
    }
  }
  return result.replace(/\{(\d+)\}/g, (_, i) =>
    String(args[Number(i)] ?? `{${i}}`),
  );
}
export function assetCount(count: number) {
  const plural = new Intl.PluralRules(locale()).select(count);
  return language === "ru"
    ? `${count} ${plural === "one" ? "материал" : plural === "few" ? "материала" : "материалов"}`
    : `${count} ${count === 1 ? "asset" : "assets"}`;
}
export const projectName = (project: { id: string; name: string }) =>
  project.id === "inbox" && project.name === "My creations"
    ? t("My creations")
    : project.name;
export function LanguageSwitch() {
  const value = useLanguage();
  return (
    <label className="language-switch">
      <Languages size={18} />
      <span className="sr-only">Language / Язык</span>
      <select
        aria-label="Language / Язык"
        value={value}
        onChange={(e) => setLanguage(e.target.value as Language)}
      >
        <option value="en">English</option>
        <option value="ru">Русский</option>
      </select>
    </label>
  );
}
