<script lang="ts">
  // Touch replay of a game's recording: big playfield, values, scrubber, speed.
  import { NextPiece, Playfield, Timeline, loadRecording, rowsFromCells, type NgfFrame } from "@nestris-ltm/nes";
  import { onMount } from "svelte";
  import { num } from "../lib/format";
  import { lang, t } from "../lib/i18n.svelte";

  let { gameId }: { gameId: number } = $props();

  const SPEEDS = [1, 2, 4, 8];

  let timeline = $state<Timeline | null>(null);
  let frame = $state<NgfFrame | null>(null);
  let position = $state(0);
  let playing = $state(false);
  let speed = $state(1);
  let error = $state(false);
  let raf = 0;

  function loop(now: number): void {
    if (timeline) {
      frame = timeline.frames[timeline.tick(now)] ?? null;
      position = timeline.position;
      playing = timeline.playing;
    }
    raf = requestAnimationFrame(loop);
  }

  function toggle(): void {
    if (!timeline) return;
    if (timeline.playing) timeline.pause();
    else timeline.play(performance.now());
  }

  function setSpeed(value: number): void {
    speed = value;
    if (timeline) timeline.speed = value;
  }

  function jump(ms: number): void {
    timeline?.seek(position + ms);
  }

  function clock(ms: number): string {
    const s = Math.floor(ms / 1000);
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  onMount(() => {
    loadRecording(`/api/games/${gameId}/recording`)
      .then(({ frames }) => {
        if (!frames.length) {
          error = true;
          return;
        }
        timeline = new Timeline(frames);
        frame = frames[0] ?? null;
        timeline.play(performance.now());
      })
      .catch(() => (error = true));
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  });
</script>

{#if error}
  <p class="muted center">{t("replay.none")}</p>
{:else if timeline && frame}
  <div class="replay">
    <button class="well" onclick={toggle} aria-label="Play/Pause">
      <Playfield rows={rowsFromCells(frame.cells)} level={frame.level} cell={30} />
      {#if !playing}<span class="paused">▶</span>{/if}
    </button>
    <div class="side">
      <div class="box">
        <span class="label">NEXT</span>
        <NextPiece piece={frame.preview} level={frame.level} cell={26} />
      </div>
      <div class="box values">
        <span class="label">SCORE</span><span class="num big">{num(frame.score, lang())}</span>
        <span class="label">LINES</span><span class="num">{num(frame.lines, lang())}</span>
        <span class="label">LEVEL</span><span class="num">{num(frame.level, lang())}</span>
      </div>
      <div class="controls">
        <input
          class="scrub"
          type="range"
          min="0"
          max={timeline.duration}
          value={position}
          oninput={(e) => timeline?.seek(Number(e.currentTarget.value))}
          aria-label="Position"
        />
        <div class="times num muted"><span>{clock(position)}</span><span>{clock(timeline.duration)}</span></div>
        <div class="row">
          <button onclick={() => jump(-10_000)}>−10s</button>
          <button class="primary play" onclick={toggle}>{playing ? "❚❚" : "▶"}</button>
          <button onclick={() => jump(10_000)}>+10s</button>
        </div>
        <div class="row">
          {#each SPEEDS as s (s)}
            <button class:on={speed === s} onclick={() => setSpeed(s)}>{s}×</button>
          {/each}
        </div>
      </div>
    </div>
  </div>
{:else}
  <p class="muted center">{t("common.loading")}</p>
{/if}

<style>
  .replay {
    display: flex;
    gap: 32px;
    justify-content: center;
    align-items: flex-start;
    height: 100%;
  }
  .well {
    position: relative;
    padding: 6px;
    background: #000;
    border: 3px solid var(--line);
    border-radius: 8px;
    min-height: 0;
  }
  .well:active:not(:disabled) {
    transform: none;
    background: #000;
  }
  .paused {
    position: absolute;
    inset: 0;
    display: grid;
    place-items: center;
    font-size: 110px;
    color: rgb(255 255 255 / 0.8);
    background: rgb(0 0 0 / 0.35);
  }
  .side {
    display: grid;
    gap: 18px;
    width: 400px;
  }
  .box {
    padding: 14px 18px;
    background: #000;
    border: 2px solid var(--line);
    border-radius: 8px;
    font-family: var(--mono);
  }
  .values {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 6px 18px;
    align-items: baseline;
    font-size: 30px;
  }
  .values .num {
    text-align: right;
  }
  .label {
    display: block;
    color: var(--muted);
    font-size: 20px;
    margin-bottom: 6px;
  }
  .big {
    font-size: 38px;
    color: var(--accent);
  }
  .controls {
    display: grid;
    gap: 12px;
  }
  .scrub {
    width: 100%;
    height: 48px;
    accent-color: var(--accent);
  }
  .times {
    display: flex;
    justify-content: space-between;
    font-size: 18px;
    margin-top: -10px;
  }
  .row button {
    flex: 1;
    padding: 0 10px;
  }
  .play {
    font-size: 30px;
  }
  button.on {
    border-color: var(--accent);
    color: var(--accent);
  }
  .center {
    text-align: center;
    margin-top: 80px;
  }
</style>
