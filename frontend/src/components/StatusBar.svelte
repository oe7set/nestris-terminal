<script lang="ts">
  // Top bar: logo (5 quick taps open the hidden admin menu), event, status.
  import { bridge } from "../lib/bridge.svelte";
  import { flow } from "../lib/flow.svelte";
  import { t } from "../lib/i18n.svelte";

  const TAPS = 5;
  const WINDOW_MS = 3000;
  let taps: number[] = [];

  function tapLogo(): void {
    const now = Date.now();
    taps = [...taps.filter((ts) => now - ts < WINDOW_MS), now];
    if (taps.length >= TAPS) {
      taps = [];
      flow.session = null;
      flow.go({ name: "admin" });
    }
  }

  let clock = $state(new Date());
  $effect(() => {
    const id = setInterval(() => (clock = new Date()), 10_000);
    return () => clearInterval(id);
  });
</script>

<header>
  <!-- Deliberately not a button: nothing hints at the hidden menu. -->
  <div class="logo" onpointerdown={tapLogo} role="presentation">
    <span class="r">RETRO</span><span class="v">VERSE</span>
  </div>
  <div class="event mono">{bridge.eventName ?? ""}</div>
  <div class="spacer"></div>
  {#if !bridge.connected}
    <span class="warn-pill">{t("status.bridge_down")}</span>
  {:else}
    {#if bridge.hostReachable === false}<span class="warn-pill">{t("status.host_down")}</span>{/if}
    {#if !bridge.readerConnected}<span class="warn-pill">{t("status.reader_down")}</span>{/if}
  {/if}
  <div class="clock mono">
    {clock.toLocaleTimeString(bridge.kiosk.lang === "en" ? "en-GB" : "de-AT", { hour: "2-digit", minute: "2-digit" })}
  </div>
</header>

<style>
  header {
    display: flex;
    align-items: center;
    gap: 18px;
    height: 76px;
    padding: 0 28px;
    border-bottom: 1px solid var(--line);
    background: linear-gradient(#11111c, var(--bg));
  }
  .logo {
    font-family: var(--mono);
    font-size: 34px;
    letter-spacing: 0.08em;
    padding: 10px 14px 10px 0;
  }
  .r {
    color: var(--accent);
  }
  .v {
    color: var(--cyan);
  }
  .event {
    color: var(--muted);
    font-size: 22px;
  }
  .warn-pill {
    padding: 6px 14px;
    border-radius: 999px;
    background: rgb(255 84 104 / 0.15);
    border: 1px solid var(--bad);
    color: var(--bad);
    font-size: 18px;
  }
  .clock {
    font-size: 26px;
    color: var(--muted);
  }
</style>
