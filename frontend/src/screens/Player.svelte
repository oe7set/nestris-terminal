<script lang="ts">
  // Player page: standing in the current event, all-time stats, event history,
  // own games with replays. Opens when a known card is placed.
  import { onMount } from "svelte";
  import { api, type GameRow, type Profile } from "../lib/api";
  import { flow } from "../lib/flow.svelte";
  import { dateTime, date, num, pct } from "../lib/format";
  import { lang, t } from "../lib/i18n.svelte";

  let { playerId }: { playerId: number } = $props();

  let profile = $state<Profile | null>(null);
  let failed = $state(false);
  let tab = $state<"games" | "events">("games");

  onMount(() => {
    api<Profile>(`/api/players/${playerId}`)
      .then((p) => (profile = p))
      .catch(() => (failed = true));
  });

  const maxEventBest = $derived(Math.max(1, ...(profile?.events.map((e) => e.best_score ?? 0) ?? [])));

  function replay(g: GameRow): void {
    if (!profile || !g.replay) return;
    flow.go({
      name: "replay",
      gameId: g.id,
      title: `${profile.player.nickname} · ${num(g.score, lang())} · ${dateTime(g.started_at, lang())}`,
      back: { name: "player", playerId },
    });
  }
</script>

<div class="screen player">
  <div class="top">
    <h1>{t("player.hello", { name: profile?.player.nickname ?? flow.session?.nickname ?? "" })}</h1>
    <span class="spacer"></span>
    <button class="primary" onclick={() => flow.go({ name: "score", playerId })}>✎ {t("player.enter_score")}</button>
    <button onclick={() => flow.menu()}>{t("player.logout")}</button>
  </div>

  {#if failed}
    <p class="error">{t("error.host")}</p>
  {:else if !profile}
    <p class="muted">{t("common.loading")}</p>
  {:else}
    <div class="cols">
      <div class="left">
        <section class="panel current">
          {#if profile.current}
            <h3>{t("player.current", { event: profile.current.event.name })}</h3>
            {#if profile.current.standing}
              {@const s = profile.current.standing}
              <div class="standing">
                <div class="rankbox">
                  <span class="label">{t("player.rank")}</span>
                  <span class="rank num">{s.rank}</span>
                  <span class="muted">{t("player.of", { n: s.players })}</span>
                </div>
                <div class="facts">
                  <div><span class="label">{t("player.best")}</span><span class="num gold">{num(s.best_score, lang())}</span></div>
                  <div><span class="label">{t("player.games")}</span><span class="num">{num(profile.current.games, lang())}</span></div>
                </div>
              </div>
              <p class="gap">
                {#if s.gap_to_next !== null}
                  {t("player.gap", { points: num(s.gap_to_next + 1, lang()), rank: s.rank - 1, name: s.next_rank_name ?? "" })}
                {:else}
                  🏆 {t("player.leader")}
                {/if}
              </p>
              {#if s.best_game_id && profile.games.some((g) => g.id === s.best_game_id && g.replay)}
                <button
                  class="ghost"
                  onclick={() =>
                    flow.go({
                      name: "replay",
                      gameId: s.best_game_id!,
                      title: `${profile!.player.nickname} · ${num(s.best_score, lang())}`,
                      back: { name: "player", playerId },
                    })}>▶ {t("player.replay")} – {t("player.best")}</button
                >
              {/if}
            {:else}
              <p class="muted">{t("player.no_event_games")}</p>
            {/if}
          {:else}
            <p class="muted">{t("menu.no_event")}</p>
          {/if}
        </section>

        <section class="panel">
          <h3>{t("player.all_time")}</h3>
          <div class="tiles">
            <div><span class="label">{t("player.best")}</span><span class="num gold">{num(profile.all_time.best_score, lang())}</span></div>
            <div><span class="label">{t("player.games")}</span><span class="num">{num(profile.all_time.games, lang())}</span></div>
            <div><span class="label">{t("player.avg")}</span><span class="num">{num(profile.all_time.avg_score, lang())}</span></div>
            <div><span class="label">{t("player.lines")}</span><span class="num">{num(profile.all_time.total_lines, lang())}</span></div>
            <div><span class="label">{t("player.trt")}</span><span class="num">{pct(profile.all_time.tetris_rate)}</span></div>
            <div><span class="label">{t("player.best_level")}</span><span class="num">{num(profile.all_time.best_level, lang())}</span></div>
          </div>
        </section>
      </div>

      <section class="panel right">
        <div class="tabs">
          <button class:on={tab === "games"} onclick={() => (tab = "games")}>{t("player.my_games")} ({profile.games.length})</button>
          <button class:on={tab === "events"} onclick={() => (tab = "events")}>{t("player.events")} ({profile.events.length})</button>
        </div>
        <div class="list scroll">
          {#if tab === "games"}
            {#each profile.games as g (g.id)}
              <button class="game" disabled={!g.replay} onclick={() => replay(g)}>
                <span class="muted">{dateTime(g.started_at, lang())}</span>
                <span class="num gscore">{num(g.score, lang())}</span>
                <span class="num muted">
                  {g.lines !== null ? `${g.lines} L` : ""}
                  {g.start_level !== null ? ` · L${g.start_level}${g.end_level !== null ? `→${g.end_level}` : ""}` : ""}
                </span>
                <span>
                  {#if g.status === "live"}<span class="badge live">{t("menu.live")}</span>{/if}
                  {#if g.source === "self_reported"}<span class="badge warn">{t("player.self_reported")}</span>{/if}
                </span>
                <span class="play">{g.replay ? "▶" : ""}</span>
              </button>
            {:else}
              <p class="muted">{t("player.no_games")}</p>
            {/each}
          {:else}
            {#each profile.events as e (e.event.id)}
              <div class="ev" class:active={e.active}>
                <div class="evhead">
                  <span>{e.event.name}</span>
                  <span class="muted small">{date(e.event.starts_at, lang())}</span>
                </div>
                <div class="bar"><span style="width: {((e.best_score ?? 0) / maxEventBest) * 100}%"></span></div>
                <div class="evfacts muted small">
                  <span class="num gold">{num(e.best_score, lang())}</span>
                  <span>{e.rank ? t("player.event_rank", { rank: e.rank, n: e.players ?? "?" }) : ""}</span>
                  <span>{num(e.games, lang())} {t("player.games")}</span>
                </div>
              </div>
            {:else}
              <p class="muted">{t("player.no_games")}</p>
            {/each}
          {/if}
        </div>
      </section>
    </div>
    <p class="muted foot">{t("player.remove_hint")}</p>
  {/if}
</div>

<style>
  .player {
    gap: 18px;
  }
  .top {
    display: flex;
    align-items: center;
    gap: 16px;
  }
  .top h1 {
    color: var(--accent);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .cols {
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: 1fr 1.15fr;
    gap: 24px;
  }
  .left {
    display: flex;
    flex-direction: column;
    gap: 20px;
    min-height: 0;
  }
  section {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .label {
    display: block;
    font-size: 17px;
    color: var(--muted);
  }
  .gold {
    color: var(--accent);
  }
  .standing {
    display: flex;
    gap: 34px;
    align-items: center;
  }
  .rankbox {
    display: grid;
    justify-items: center;
    padding: 10px 26px;
    border: 2px solid var(--accent);
    border-radius: var(--radius);
  }
  .rank {
    font-size: 80px;
    line-height: 1;
    color: var(--accent);
  }
  .facts {
    display: grid;
    gap: 12px;
    font-size: 34px;
  }
  .gap {
    font-size: 22px;
    color: var(--cyan);
  }
  .tiles {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px 20px;
    font-size: 28px;
  }
  .right {
    min-height: 0;
  }
  .tabs {
    display: flex;
    gap: 10px;
  }
  .tabs button {
    flex: 1;
  }
  .tabs button.on {
    border-color: var(--accent);
    color: var(--accent);
  }
  .list {
    flex: 1;
    min-height: 0;
    display: grid;
    gap: 8px;
    align-content: start;
    padding-right: 6px;
  }
  .game {
    display: grid;
    grid-template-columns: 170px 150px 1fr auto 34px;
    gap: 12px;
    align-items: center;
    text-align: left;
    padding: 0 16px;
    border-width: 1px;
    font-size: 20px;
  }
  .game:disabled {
    opacity: 1;
  }
  .gscore {
    font-size: 26px;
    color: var(--accent);
    text-align: right;
  }
  .play {
    color: var(--cyan);
  }
  .ev {
    padding: 12px 16px;
    border: 1px solid var(--line);
    border-radius: var(--radius);
    display: grid;
    gap: 8px;
  }
  .ev.active {
    border-color: var(--accent);
  }
  .evhead,
  .evfacts {
    display: flex;
    justify-content: space-between;
    gap: 14px;
  }
  .bar {
    height: 12px;
    background: var(--panel-2);
    border-radius: 6px;
    overflow: hidden;
  }
  .bar span {
    display: block;
    height: 100%;
    background: linear-gradient(90deg, var(--cyan), var(--accent));
  }
  .small {
    font-size: 17px;
  }
  .foot {
    text-align: center;
    font-size: 18px;
  }
</style>
