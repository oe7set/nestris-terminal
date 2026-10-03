<script lang="ts">
  // Main menu: highscore of the current event, "place your card", sign up.
  import { onMount } from "svelte";
  import { api, type Highscore, type HighscoreEntry } from "../lib/api";
  import { bridge } from "../lib/bridge.svelte";
  import { flow } from "../lib/flow.svelte";
  import { num } from "../lib/format";
  import { lang, t } from "../lib/i18n.svelte";

  const REFRESH_MS = 10_000;

  let data = $state<Highscore | null>(null);
  let failed = $state(false);

  async function load(): Promise<void> {
    try {
      data = await api<Highscore>("/api/highscore");
      failed = false;
    } catch {
      failed = true;
    }
  }

  function open(entry: HighscoreEntry): void {
    if (!entry.game_id) return;
    flow.go({
      name: "replay",
      gameId: entry.game_id,
      title: `#${entry.rank} ${entry.nickname} · ${num(entry.score, lang())}`,
      back: { name: "menu" },
    });
  }

  onMount(() => {
    void load();
    const id = setInterval(() => void load(), REFRESH_MS);
    const off = bridge.on((e) => {
      if (e.type === "host" && e.reachable) void load();
    });
    return () => {
      clearInterval(id);
      off();
    };
  });
</script>

<div class="screen menu">
  <section class="board panel">
    <div class="head">
      <h2>{t("menu.highscore")}</h2>
      <span class="muted">
        {#if data?.event}
          {t("menu.games", { n: num(data.stats.total_games, lang()), p: num(data.stats.active_players, lang()) })}
        {:else if data}
          {t("menu.no_event")}
        {/if}
      </span>
    </div>
    {#if data && data.entries.length}
      <p class="muted hint">{t("menu.tap_replay")}</p>
      <ol class="list scroll">
        {#each data.entries as e (e.user_id)}
          <li>
            <button class="entry" class:top={e.rank <= 3} disabled={!e.game_id} onclick={() => open(e)}>
              <span class="rank num r{e.rank}">{e.rank}</span>
              <span class="name">{e.nickname}</span>
              {#if e.is_live}<span class="badge live">{t("menu.live")}</span>{/if}
              <span class="lv num muted">{e.level !== null ? `L${e.level}` : ""}</span>
              <span class="score num">{num(e.score, lang())}</span>
              <span class="play">{e.game_id ? "▶" : ""}</span>
            </button>
          </li>
        {/each}
      </ol>
    {:else if data}
      <p class="muted empty">{t("menu.empty")}</p>
    {:else if failed}
      <p class="error empty">{t("error.host")}</p>
    {:else}
      <p class="muted empty">{t("common.loading")}</p>
    {/if}
  </section>

  <aside>
    <div class="cta panel">
      <div class="card-anim" aria-hidden="true">
        <div class="reader"></div>
        <div class="card"><span>NES</span></div>
      </div>
      <p class="place">{t("menu.place_card")}</p>
    </div>
    <button class="primary big" onclick={() => flow.go({ name: "register", card: null })}>
      ＋ {t("menu.register")}
    </button>
  </aside>
</div>

<style>
  .menu {
    flex-direction: row;
    gap: 28px;
  }
  .board {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 20px;
  }
  .hint {
    font-size: 17px;
  }
  .list {
    list-style: none;
    margin: 6px 0 0;
    padding: 0 6px 0 0;
    display: grid;
    gap: 8px;
    flex: 1;
    align-content: start;
  }
  .entry {
    width: 100%;
    display: grid;
    grid-template-columns: 70px 1fr auto 70px 190px 40px;
    gap: 14px;
    align-items: center;
    text-align: left;
    padding: 0 18px;
    min-height: 68px;
    background: var(--panel-2);
    border-width: 1px;
  }
  .entry:disabled {
    opacity: 1;
  }
  .entry.top {
    border-color: rgb(255 199 64 / 0.4);
  }
  .rank {
    font-size: 30px;
    color: var(--muted);
  }
  .r1 {
    color: #ffd700;
  }
  .r2 {
    color: #d0d6e0;
  }
  .r3 {
    color: #e0975a;
  }
  .name {
    font-size: 28px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .score {
    font-size: 30px;
    text-align: right;
    color: var(--accent);
  }
  .lv {
    font-size: 20px;
    text-align: right;
  }
  .play {
    color: var(--cyan);
    text-align: center;
  }
  .empty {
    margin: 60px auto;
  }
  aside {
    width: 520px;
    display: flex;
    flex-direction: column;
    gap: 24px;
  }
  .cta {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 34px;
    text-align: center;
  }
  .place {
    font-size: 32px;
    max-width: 400px;
  }
  .card-anim {
    position: relative;
    width: 260px;
    height: 240px;
  }
  .reader {
    position: absolute;
    left: 20px;
    right: 20px;
    bottom: 0;
    height: 70px;
    border-radius: 16px;
    background: linear-gradient(#2a2a40, #15151f);
    border: 2px solid var(--line);
    box-shadow: 0 0 40px rgb(79 214 255 / 0.25);
  }
  .card {
    position: absolute;
    left: 55px;
    width: 150px;
    height: 95px;
    border-radius: 12px;
    background: linear-gradient(135deg, var(--accent), #ff7a3d);
    color: var(--accent-ink);
    font: 700 26px var(--mono);
    display: grid;
    place-items: center;
    animation: tap 2.6s ease-in-out infinite;
  }
  @keyframes tap {
    0%,
    100% {
      top: 0;
      transform: rotate(-8deg);
    }
    45%,
    65% {
      top: 115px;
      transform: rotate(0);
    }
  }
</style>
