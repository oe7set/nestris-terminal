<script lang="ts">
  // Hidden menu, tab "Karten": clear mode (every card placed is wiped and
  // unlinked on the host) and a new card for an existing player.
  import { onMount } from "svelte";
  import TextField from "./TextField.svelte";
  import { api, ApiError } from "../lib/api";
  import { bridge } from "../lib/bridge.svelte";
  import { t, type Key } from "../lib/i18n.svelte";

  let { onError }: { onError: (e: unknown) => void } = $props();

  interface PlayerRef {
    id: number;
    nickname: string;
  }
  interface ClearResult {
    uid: string;
    name: string | null;
    erased: boolean;
    player: PlayerRef | null;
  }
  interface Entry {
    uid: string;
    ok: boolean;
    text: string;
  }

  // An admin error the crew can act on, else the bridge's message.
  function errorText(e: unknown): string {
    if (e instanceof ApiError) {
      if (e.detail === "reader_fw_old" || e.detail === "host_old") return t(`cards.${e.detail}` as Key);
      return e.detail;
    }
    return String(e);
  }

  // ---------------------------------------------------------------- clear mode

  let clearing = $state(false);
  let busyUid = $state<string | null>(null);
  let doneUid: string | null = null; // stays on the reader after clearing: not again
  let history = $state<Entry[]>([]);

  function log(entry: Entry): void {
    history = [entry, ...history].slice(0, 12);
  }

  async function clearCard(uid: string, format: string): Promise<void> {
    if (!clearing || issuing || busyUid !== null || uid === doneUid) return;
    doneUid = uid;
    if (format === "unsupported") {
      log({ uid, ok: false, text: t("cards.unsupported") });
      return;
    }
    busyUid = uid;
    try {
      const r = await api<ClearResult>("/local/admin/cards/clear", { method: "POST", body: { uid } });
      const owner = r.player?.nickname ?? null;
      let text: string;
      if (r.erased) text = owner ? t("cards.cleared_from", { name: owner }) : t("cards.cleared");
      else text = owner ? t("cards.unlinked", { name: owner }) : t("cards.was_blank");
      log({ uid, ok: true, text });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onError(e);
      log({ uid, ok: false, text: errorText(e) });
    } finally {
      busyUid = null;
    }
  }

  function toggleClearing(): void {
    clearing = !clearing;
    doneUid = null;
    // A card already lying on the reader is the first one.
    if (clearing && bridge.card) void clearCard(bridge.card.uid, bridge.card.format ?? "unreadable");
  }

  onMount(() =>
    bridge.on((e) => {
      if (e.type !== "card") return;
      if (e.state === "removed") {
        if (e.uid === doneUid) doneUid = null;
        return;
      }
      void clearCard(e.uid as string, (e.format as string) ?? "unreadable");
    }),
  );

  // ---------------------------------------------------------------- new card for a player

  let query = $state("");
  let players = $state<(PlayerRef & { cards: number })[] | null>(null);
  let selected = $state<PlayerRef | null>(null);
  let issuing = $state(false);
  let issueResult = $state<Entry | null>(null);

  async function search(): Promise<void> {
    const q = query.trim();
    if (!q) {
      players = null;
      return;
    }
    try {
      const r = await api<{ players: (PlayerRef & { cards: number })[] }>("/local/admin/players", { query: { q } });
      if (q === query.trim()) players = r.players;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onError(e);
      issueResult = { uid: "", ok: false, text: errorText(e) };
    }
  }

  // Search while typing (on-screen keyboard), a little delayed.
  $effect(() => {
    const q = query.trim();
    if (q.length < 2) {
      players = null;
      return;
    }
    const id = setTimeout(() => void search(), 300);
    return () => clearTimeout(id);
  });

  function pick(p: PlayerRef): void {
    selected = { id: p.id, nickname: p.nickname };
    issueResult = null;
  }

  async function issue(): Promise<void> {
    if (!selected) return;
    clearing = false; // the new card must not be wiped right away
    issuing = true;
    issueResult = null;
    try {
      const r = await api<{ card: { uid: string }; player: PlayerRef; previous: PlayerRef | null }>(
        "/local/admin/cards/issue",
        { method: "POST", body: { player_id: selected.id, nickname: selected.nickname } },
      );
      let text = t("cards.issued", { name: r.player.nickname });
      if (r.previous) text += " " + t("cards.previous", { name: r.previous.nickname });
      issueResult = { uid: r.card.uid, ok: true, text };
      selected = null;
      query = "";
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) onError(e);
      issueResult = { uid: "", ok: false, text: errorText(e) };
    } finally {
      issuing = false;
    }
  }
</script>

<div class="cards">
  <section class="panel">
    <h3>{t("cards.clear_title")}</h3>
    <p class="muted small">{t("cards.clear_hint")}</p>
    <div class="row">
      <button class={clearing ? "danger" : "primary"} disabled={issuing} onclick={toggleClearing}>
        {clearing ? t("cards.clear_stop") : t("cards.clear_start")}
      </button>
      {#if clearing}
        <span class="active">{busyUid ? t("cards.clearing") : t("cards.clear_active")}</span>
      {/if}
    </div>
    {#if history.length}
      <ul class="history">
        {#each history as h, i (i)}
          <li class:bad={!h.ok}><span class="mono uid">{h.uid}</span><span>{h.ok ? "✓" : "✕"} {h.text}</span></li>
        {/each}
      </ul>
    {/if}
  </section>

  <section class="panel">
    <h3>{t("cards.issue_title")}</h3>
    <p class="muted small">{t("cards.issue_hint")}</p>
    {#if selected}
      <div class="row">
        <button class="primary big" disabled={issuing} onclick={issue}>
          {issuing ? t("cards.waiting") : t("cards.write_for", { name: selected.nickname })}
        </button>
        <button disabled={issuing} onclick={() => (selected = null)}>{t("common.cancel")}</button>
      </div>
    {:else}
      <TextField id="card_search" label={t("cards.search")} bind:value={query} maxLength={40} onEnter={search} />
      {#if players}
        <div class="results">
          {#each players as p (p.id)}
            <button class="player" onclick={() => pick(p)}>
              <span>{p.nickname}</span>
              <span class="muted small">{t("cards.n_cards", { n: p.cards })}</span>
            </button>
          {:else}
            <p class="muted">{t("cards.no_players")}</p>
          {/each}
        </div>
      {/if}
    {/if}
    {#if issueResult}<p class={issueResult.ok ? "ok" : "error"}>{issueResult.ok ? "✓" : "✕"} {issueResult.text}</p>{/if}
  </section>
</div>

<style>
  .cards {
    display: grid;
    gap: 16px;
    max-width: 1100px;
  }
  section {
    display: grid;
    gap: 12px;
  }
  .small {
    font-size: 17px;
  }
  .active {
    color: var(--bad);
    animation: pulse 1.2s ease-in-out infinite;
  }
  .history {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 6px;
    font-size: 18px;
  }
  .history li {
    display: flex;
    gap: 14px;
    color: var(--ok);
  }
  .history li.bad {
    color: var(--bad);
  }
  .uid {
    color: var(--muted);
    min-width: 130px;
  }
  .results {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 10px;
  }
  .player {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
    text-align: left;
  }
</style>
