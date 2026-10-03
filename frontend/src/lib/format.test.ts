import { describe, expect, it } from "vitest";
import { EMAIL_RE, NICKNAME_RE, num, pct } from "./format";
import { t } from "./i18n.svelte";

describe("format", () => {
  it("formats numbers per language", () => {
    expect(num(1234567)).toMatch(/^1\D234\D567$/); // de-AT groups with a (narrow) space
    expect(num(1234567, "en")).toBe("1,234,567");
    expect(num(null)).toBe("–");
    expect(pct(0.456)).toBe("46 %");
  });

  it("follows the NestrisLTM nickname rules", () => {
    expect(NICKNAME_RE.test("Erwin")).toBe(true);
    expect(NICKNAME_RE.test("a")).toBe(false);
    expect(NICKNAME_RE.test("Jürgen")).toBe(false); // ASCII only: it goes onto the card
    expect(NICKNAME_RE.test("x".repeat(16))).toBe(false);
    expect(EMAIL_RE.test("a@b.at")).toBe(true);
    expect(EMAIL_RE.test("a@b")).toBe(false);
  });
});

describe("i18n", () => {
  it("fills parameters", () => {
    expect(t("player.event_rank", { rank: 3, n: 40 })).toBe("Platz 3 von 40");
    expect(t("reg.welcome", { name: "Erwin" })).toBe("Willkommen, Erwin!");
  });
});
