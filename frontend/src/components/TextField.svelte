<script lang="ts">
  // A text field for the on-screen keyboard: tapping it makes it the keyboard target.
  // It is not a real <input>, so the OS touch keyboard never pops up; a
  // physical keyboard types into it too (App.svelte -> input.handleKey).
  import { onMount } from "svelte";
  import { input, type FieldTarget, type KeyboardLayout } from "../lib/input.svelte";

  interface Props {
    id: string;
    label: string;
    value: string;
    layout?: KeyboardLayout;
    maxLength?: number;
    secret?: boolean;
    hint?: string | null;
    error?: string | null;
    ok?: string | null;
    onEnter?: () => void;
    autofocus?: boolean;
  }
  let {
    id,
    label,
    value = $bindable(),
    layout = "text",
    maxLength = 64,
    secret = false,
    hint = null,
    error = null,
    ok = null,
    onEnter,
    autofocus = false,
  }: Props = $props();

  const focused = $derived(input.target?.id === id);

  // One target for the on-screen and a physical keyboard; getters, so prop
  // changes (e.g. a new onEnter) are seen.
  const target: FieldTarget = {
    get id() {
      return id;
    },
    get: () => value,
    set: (v) => (value = v),
    get layout() {
      return layout;
    },
    get maxLength() {
      return maxLength;
    },
    get onEnter() {
      return onEnter;
    },
  };

  function focus(): void {
    input.focus(target);
  }

  onMount(() => {
    const unregister = input.register(target);  // Tab order = order on screen
    if (autofocus) focus();
    return unregister;
  });

  const shown = $derived(secret ? "•".repeat(value.length) : value);
</script>

<div class="field">
  <span class="label">{label}</span>
  <button type="button" class="box" class:focused class:bad={!!error} onclick={focus}>
    <span class="value">{shown}</span>{#if focused}<span class="caret"></span>{/if}
  </button>
  {#if error}
    <span class="msg error">{error}</span>
  {:else if ok}
    <span class="msg ok">✓ {ok}</span>
  {:else if hint}
    <span class="msg muted">{hint}</span>
  {/if}
</div>

<style>
  .field {
    display: grid;
    gap: 6px;
  }
  .label {
    font-size: 18px;
    color: var(--muted);
  }
  .box {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    width: 100%;
    min-height: 72px;
    padding: 0 20px;
    background: #0b0b14;
    font-size: 28px;
    text-align: left;
  }
  .box:active:not(:disabled) {
    transform: none;
  }
  .box.focused {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgb(255 199 64 / 0.2);
  }
  .box.bad {
    border-color: var(--bad);
  }
  .value {
    white-space: pre;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .caret {
    width: 3px;
    height: 34px;
    margin-left: 2px;
    background: var(--accent);
    animation: blink 1s steps(1) infinite;
  }
  .msg {
    font-size: 17px;
  }
  @keyframes blink {
    50% {
      opacity: 0;
    }
  }
</style>
