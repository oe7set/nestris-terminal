// Live state from the bridge WebSocket: card on the reader, reader and host status.

export interface CardInfo {
  uid: string;
  name: string | null;
}

export interface KioskConfig {
  fullscreen: boolean;
  hide_cursor: boolean;
  lang: "de" | "en";
  card_grace_s: number;
  idle_timeout_s: number;
}

type Listener = (event: { type: string; [key: string]: unknown }) => void;

class Bridge {
  connected = $state(false);
  card = $state<CardInfo | null>(null);
  readerConnected = $state(false);
  hostReachable = $state<boolean | null>(null);
  hostError = $state<string | null>(null);
  eventName = $state<string | null>(null);
  version = $state("");
  kiosk = $state<KioskConfig>({
    fullscreen: true,
    hide_cursor: false,
    lang: "de",
    card_grace_s: 3,
    idle_timeout_s: 120,
  });

  #listeners: Listener[] = [];
  #retry = 500;

  on(listener: Listener): () => void {
    this.#listeners.push(listener);
    return () => {
      this.#listeners = this.#listeners.filter((l) => l !== listener);
    };
  }

  start(): void {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onopen = () => {
      this.connected = true;
      this.#retry = 500;
    };
    ws.onmessage = (e) => this.#handle(JSON.parse(e.data as string));
    ws.onclose = () => {
      this.connected = false;
      setTimeout(() => this.start(), this.#retry);
      this.#retry = Math.min(this.#retry * 2, 5000);
    };
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  #handle(msg: any): void {
    switch (msg.type) {
      case "state": {
        const s = msg.data;
        this.version = s.version;
        this.kiosk = s.kiosk;
        this.readerConnected = s.reader.connected;
        this.hostReachable = s.host.reachable;
        this.hostError = s.host.error;
        this.eventName = s.host.event?.name ?? null;
        this.card = s.reader.card ?? null;
        // A card already lying on the reader when the UI (re)loads.
        if (s.reader.card) this.#emit({ type: "card", state: "present", ...s.reader.card });
        break;
      }
      case "card":
        this.card = msg.state === "present" ? { uid: msg.uid, name: msg.name } : null;
        break;
      case "reader":
        this.readerConnected = msg.connected;
        break;
      case "host":
        this.hostReachable = msg.reachable;
        this.hostError = msg.error;
        break;
      case "config":
        this.kiosk = msg.kiosk;
        break;
    }
    this.#emit(msg);
  }

  #emit(msg: { type: string; [key: string]: unknown }): void {
    if (msg.type === "card" && msg.state === "present") this.card = { uid: msg.uid as string, name: (msg.name as string) ?? null };
    for (const l of this.#listeners) l(msg);
  }
}

export const bridge = new Bridge();
