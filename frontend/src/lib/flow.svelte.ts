// Which screen is shown, driven by touches and by cards on the reader.
//
// - A known card (or an old card whose name is a nickname) opens the player
//   page; a blank/unknown card opens the registration.
// - The player's "session" lasts while the card lies on the reader; when it
//   leaves, a grace period starts, then the main menu returns.
// - Without touches for idle_timeout_s every screen falls back to the menu.
// - The registration and the admin menu handle cards themselves.

import { api, ApiError, type CardLookup } from "./api";
import { bridge, type CardInfo } from "./bridge.svelte";

export type Screen =
  | { name: "menu" }
  | { name: "player"; playerId: number }
  | { name: "score"; playerId: number }
  | { name: "replay"; gameId: number; title: string; back: Screen }
  | { name: "register"; card: CardInfo | null }
  | { name: "admin" };

export interface Session {
  playerId: number;
  nickname: string;
  uid: string;
}

class Flow {
  screen = $state<Screen>({ name: "menu" });
  session = $state<Session | null>(null);
  busy = $state(false);
  notice = $state<{ kind: "error" | "info"; key: string; detail?: string } | null>(null);

  #lastTouch = Date.now();
  #grace: ReturnType<typeof setTimeout> | null = null;
  #lookupSeq = 0;

  start(): void {
    addEventListener("pointerdown", () => this.touch(), { capture: true });
    bridge.on((e) => {
      if (e.type !== "card") return;
      if (e.state === "present") void this.cardPresent({ uid: e.uid as string, name: (e.name as string) ?? null, format: e.format as string });
      else this.cardRemoved();
    });
    setInterval(() => this.#checkIdle(), 1000);
  }

  touch(): void {
    this.#lastTouch = Date.now();
  }

  go(screen: Screen): void {
    this.screen = screen;
    this.notice = null;
    this.touch();
  }

  menu(): void {
    this.session = null;
    this.go({ name: "menu" });
  }

  #checkIdle(): void {
    if (this.screen.name === "menu") return;
    if (Date.now() - this.#lastTouch > bridge.kiosk.idle_timeout_s * 1000) {
      // A card still on the reader keeps its player page open.
      if (this.session && bridge.card?.uid === this.session.uid && this.screen.name === "player") return;
      this.menu();
    }
  }

  async cardPresent(card: CardInfo): Promise<void> {
    if (this.#grace) {
      clearTimeout(this.#grace);
      this.#grace = null;
    }
    const current = this.screen.name;
    if (current === "register" || current === "admin") return; // they handle cards
    if (this.session?.uid === card.uid) return; // same card back on the reader
    if (card.format === "unsupported") {
      // e.g. a phone or a bank card: not a player card.
      this.notice = { kind: "info", key: "error.unsupported_card" };
      return;
    }
    const seq = ++this.#lookupSeq;
    this.busy = true;
    try {
      const found = await api<CardLookup>(`/api/card/${encodeURIComponent(card.uid)}`, {
        query: card.name ? { name: card.name } : undefined,
      });
      if (seq !== this.#lookupSeq) return;
      if (found.status === "unknown" || !found.player) {
        this.session = null;
        this.go({ name: "register", card });
        return;
      }
      if (found.status === "name_match") {
        // An old card with a name but an unknown uid: remember the uid.
        await api(`/api/card/${encodeURIComponent(card.uid)}/link`, {
          method: "POST",
          body: { player_id: found.player.id },
        });
      }
      this.session = { playerId: found.player.id, nickname: found.player.nickname, uid: card.uid };
      this.go({ name: "player", playerId: found.player.id });
    } catch (e) {
      this.notice = {
        kind: "error",
        key: e instanceof ApiError && e.status === 0 ? "error.bridge" : "error.host",
        detail: e instanceof Error ? e.message : String(e),
      };
    } finally {
      if (seq === this.#lookupSeq) this.busy = false;
    }
  }

  cardRemoved(): void {
    const session = this.session;
    if (!session) return;
    if (this.#grace) clearTimeout(this.#grace);
    this.#grace = setTimeout(() => {
      this.#grace = null;
      if (this.session === session && bridge.card?.uid !== session.uid) this.menu();
    }, bridge.kiosk.card_grace_s * 1000);
  }
}

export const flow = new Flow();
