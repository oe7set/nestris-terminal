<script lang="ts">
  import ReplayPlayer from "../components/ReplayPlayer.svelte";
  import { flow, type Screen } from "../lib/flow.svelte";
  import { t } from "../lib/i18n.svelte";

  let { gameId, title, back }: { gameId: number; title: string; back: Screen } = $props();
</script>

<div class="screen replay">
  <div class="top">
    <button onclick={() => flow.go(back)}>← {t("common.back")}</button>
    <h2>{t("replay.title")}: {title}</h2>
  </div>
  <div class="body">
    <ReplayPlayer {gameId} />
  </div>
</div>

<style>
  .replay {
    gap: 18px;
  }
  .top {
    display: flex;
    align-items: center;
    gap: 24px;
  }
  .top h2 {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .body {
    flex: 1;
    min-height: 0;
  }
</style>
