<script lang="ts">
  import { onMount } from "svelte";
  import Keyboard from "./components/Keyboard.svelte";
  import StatusBar from "./components/StatusBar.svelte";
  import { bridge } from "./lib/bridge.svelte";
  import { flow } from "./lib/flow.svelte";
  import { t, type Key } from "./lib/i18n.svelte";
  import { input } from "./lib/input.svelte";
  import Admin from "./screens/Admin.svelte";
  import Menu from "./screens/Menu.svelte";
  import Player from "./screens/Player.svelte";
  import Register from "./screens/Register.svelte";
  import Replay from "./screens/Replay.svelte";
  import ScoreEntry from "./screens/ScoreEntry.svelte";

  onMount(() => {
    bridge.start();
    flow.start();
  });

  $effect(() => {
    document.body.style.cursor = bridge.kiosk.hide_cursor ? "none" : "";
    document.documentElement.lang = bridge.kiosk.lang;
  });
</script>

<div class="app" class:kb={input.target !== null}>
  <StatusBar />
  <main>
    {#key flow.screen}
      {#if flow.screen.name === "menu"}
        <Menu />
      {:else if flow.screen.name === "player"}
        <Player playerId={flow.screen.playerId} />
      {:else if flow.screen.name === "score"}
        <ScoreEntry playerId={flow.screen.playerId} />
      {:else if flow.screen.name === "replay"}
        <Replay gameId={flow.screen.gameId} title={flow.screen.title} back={flow.screen.back} />
      {:else if flow.screen.name === "register"}
        <Register card={flow.screen.card} />
      {:else if flow.screen.name === "admin"}
        <Admin />
      {/if}
    {/key}
  </main>
  {#if input.target}
    <Keyboard />
  {/if}

  {#if flow.busy}
    <div class="overlay"><div class="spinner"></div></div>
  {/if}
  {#if flow.notice}
    <div class="overlay" role="alertdialog">
      <div class="notice panel">
        <p class={flow.notice.kind === "error" ? "error" : ""}>{t(flow.notice.key as Key)}</p>
        {#if flow.notice.detail}<p class="muted small">{flow.notice.detail}</p>{/if}
        <button class="primary" onclick={() => (flow.notice = null)}>{t("common.ok")}</button>
      </div>
    </div>
  {/if}
</div>

<style>
  .app {
    height: 100%;
    display: grid;
    grid-template-rows: auto 1fr auto;
  }
  main {
    min-height: 0;
    padding: 18px 28px 24px;
  }
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 50;
    display: grid;
    place-items: center;
    background: rgb(0 0 0 / 0.6);
  }
  .notice {
    max-width: 640px;
    display: grid;
    gap: 18px;
    justify-items: center;
    text-align: center;
  }
  .small {
    font-size: 16px;
  }
  .spinner {
    width: 72px;
    height: 72px;
    border: 6px solid var(--line);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.9s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
