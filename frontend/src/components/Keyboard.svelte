<script lang="ts">
  // On-screen QWERTZ keyboard for the focused TextField (the touch PC has no keyboard).
  import { t } from "../lib/i18n.svelte";
  import { input } from "../lib/input.svelte";

  let shift = $state(false);
  let caps = $state(false);
  let lastShiftTap = 0;

  const layout = $derived(input.target?.layout ?? "text");

  const rows = $derived.by(() => {
    const digits = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"];
    if (layout === "number") return [digits.slice(0, 5), digits.slice(5), ["."]];
    const letters = [
      ["q", "w", "e", "r", "t", "z", "u", "i", "o", "p", "ü"],
      ["a", "s", "d", "f", "g", "h", "j", "k", "l", "ö", "ä"],
      ["y", "x", "c", "v", "b", "n", "m", "ß"],
    ];
    return [digits, ...letters];
  });

  const extras = $derived(
    layout === "email"
      ? ["@", ".", "-", "_", ".at", ".com"]
      : layout === "url"
        ? [":", "/", ".", "-", "_", "http://"]
        : layout === "number"
          ? []
          : [".", "-", "_"],
  );

  const upper = $derived(shift || caps);

  function label(key: string): string {
    return upper && key.length === 1 ? key.toUpperCase() : key;
  }

  function press(key: string): void {
    input.type(label(key));
    if (shift && !caps) shift = false;
  }

  function toggleShift(): void {
    const now = Date.now();
    if (now - lastShiftTap < 350) {
      caps = !caps; // double tap: caps lock
      shift = false;
    } else if (caps) {
      caps = false;
    } else {
      shift = !shift;
    }
    lastShiftTap = now;
  }

  // Key repeat for backspace while held.
  let repeat: ReturnType<typeof setTimeout> | null = null;
  function backspaceDown(): void {
    input.backspace();
    const again = (delay: number) => {
      repeat = setTimeout(() => {
        input.backspace();
        again(70);
      }, delay);
    };
    again(450);
  }
  function backspaceUp(): void {
    if (repeat) clearTimeout(repeat);
    repeat = null;
  }

  // Keep the field focused: pressing keys must not blur anything.
  function keep(e: PointerEvent): void {
    e.preventDefault();
  }
</script>

<div class="kb" class:narrow={layout === "number"} onpointerdown={keep} role="group" aria-label="keyboard">
  {#each rows as row, i (i)}
    <div class="kr">
      {#if i === 3 && layout !== "number"}
        <button class="mod" class:on={shift || caps} class:caps onclick={toggleShift} aria-label="Shift">⇧</button>
      {/if}
      {#each row as key (key)}
        <button class="key" onclick={() => press(key)}>{label(key)}</button>
      {/each}
      {#if i === rows.length - 1}
        <button
          class="mod"
          onpointerdown={backspaceDown}
          onpointerup={backspaceUp}
          onpointerleave={backspaceUp}
          onpointercancel={backspaceUp}
          aria-label="Backspace">⌫</button
        >
      {/if}
    </div>
  {/each}
  <div class="kr">
    {#each extras as key (key)}
      <button class="key" onclick={() => input.type(key)}>{key}</button>
    {/each}
    {#if layout === "text"}
      <button class="key space" onclick={() => input.type(" ")}>{t("kb.space")}</button>
    {/if}
    <button class="primary done" onclick={() => (input.target?.onEnter ? input.enter() : input.blur())}>
      {t("kb.done")}
    </button>
  </div>
</div>

<style>
  .kb {
    display: grid;
    gap: 8px;
    padding: 12px 16px 16px;
    background: #0c0c15;
    border-top: 2px solid var(--line);
    animation: slide 0.15s ease-out;
  }
  .kr {
    display: flex;
    justify-content: center;
    gap: 8px;
  }
  button {
    min-width: 0;
    padding: 0;
    height: 68px;
    font-size: 28px;
  }
  .key {
    flex: 0 1 84px;
  }
  .narrow .key {
    flex-basis: 110px;
  }
  .mod {
    flex: 0 1 120px;
    background: var(--panel);
  }
  .mod.on {
    border-color: var(--accent);
    color: var(--accent);
  }
  .mod.caps {
    background: var(--accent);
    color: var(--accent-ink);
  }
  .space {
    flex: 0 1 420px;
    font-size: 20px;
    color: var(--muted);
  }
  .done {
    flex: 0 1 200px;
  }
  @keyframes slide {
    from {
      transform: translateY(100%);
    }
  }
</style>
