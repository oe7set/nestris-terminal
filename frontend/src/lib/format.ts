export function num(value: number | null | undefined, lang = "de"): string {
  if (value === null || value === undefined) return "–";
  return Math.round(value).toLocaleString(lang === "en" ? "en-GB" : "de-AT");
}

export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return `${Math.round(value * 100)} %`;
}

export function date(value: string | null | undefined, lang = "de"): string {
  if (!value) return "–";
  return new Date(value).toLocaleDateString(lang === "en" ? "en-GB" : "de-AT", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export function dateTime(value: string | null | undefined, lang = "de"): string {
  if (!value) return "–";
  return new Date(value).toLocaleString(lang === "en" ? "en-GB" : "de-AT", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Nickname rules of NestrisLTM (ASCII, it is written onto the card). */
export const NICKNAME_RE = /^[A-Za-z0-9][A-Za-z0-9 ._-]{1,14}$/;
export const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
