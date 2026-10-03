<script lang="ts">
  // Number pad for PINs, scores and levels.
  interface Props {
    value: string;
    maxLength?: number;
    onEnter?: () => void;
    enterLabel?: string;
    enterDisabled?: boolean;
  }
  let { value = $bindable(), maxLength = 8, onEnter, enterLabel = "OK", enterDisabled = false }: Props = $props();

  function press(d: string): void {
    if (value.length >= maxLength) return;
    value = value === "0" ? d : value + d;
  }
</script>

<div class="pad">
  {#each ["1", "2", "3", "4", "5", "6", "7", "8", "9"] as d (d)}
    <button onclick={() => press(d)}>{d}</button>
  {/each}
  <button class="mod" onclick={() => (value = value.slice(0, -1))} aria-label="Backspace">⌫</button>
  <button onclick={() => press("0")}>0</button>
  {#if onEnter}
    <button class="primary" disabled={enterDisabled} onclick={onEnter}>{enterLabel}</button>
  {:else}
    <button class="mod" onclick={() => (value = "")} aria-label="Clear">C</button>
  {/if}
</div>

<style>
  .pad {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 10px;
    width: min(100%, 380px);
  }
  button {
    height: 84px;
    padding: 0;
    font-family: var(--mono);
    font-size: 36px;
  }
  .mod {
    background: var(--panel);
  }
</style>
