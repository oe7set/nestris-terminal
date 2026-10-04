<script lang="ts">
  // Number pad for PINs, scores and levels.
  import { input } from "../lib/input.svelte";
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

  // Digits, Backspace and Enter from a physical keyboard (incl. the numeric
  // block), unless a text field has the keyboard.
  function onKeydown(e: KeyboardEvent): void {
    if (input.target !== null || e.ctrlKey || e.altKey || e.metaKey) return;
    if (/^[0-9]$/.test(e.key)) press(e.key);
    else if (e.key === "Backspace") value = value.slice(0, -1);
    else if (e.key === "Delete" || e.key === "Escape") value = "";
    else if (e.key === "Enter" && onEnter && !enterDisabled) onEnter();
    else return;
    e.preventDefault();
  }
</script>

<svelte:window onkeydown={onKeydown} />

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
