<script lang="ts">
  // A score the player enters by hand (forgotten card, or just because).
  import NumPad from "../components/NumPad.svelte";
  import { api, ApiError } from "../lib/api";
  import { flow } from "../lib/flow.svelte";
  import { num } from "../lib/format";
  import { lang, t } from "../lib/i18n.svelte";

  let { playerId }: { playerId: number } = $props();

  type Field = "score" | "level" | "lines";
  const LIMITS: Record<Field, number> = { score: 7, level: 2, lines: 4 };
  const LEVELS = [0, 9, 12, 15, 18, 19, 29];

  let values = $state<Record<Field, string>>({ score: "", level: "18", lines: "" });
  let field = $state<Field>("score");
  let confirming = $state(false);
  let saving = $state(false);
  let done = $state(false);
  let error = $state<string | null>(null);

  const score = $derived(Number(values.score || 0));
  const level = $derived(values.level === "" ? null : Number(values.level));
  const valid = $derived(score > 0 && score <= 9_999_999 && (level === null || level <= 29));

  async function save(): Promise<void> {
    saving = true;
    error = null;
    try {
      await api(`/api/players/${playerId}/games`, {
        method: "POST",
        body: {
          score,
          start_level: level,
          lines: values.lines === "" ? null : Number(values.lines),
        },
      });
      done = true;
      setTimeout(() => {
        if (flow.screen.name === "score") flow.go({ name: "player", playerId });
      }, 1800);
    } catch (e) {
      error = e instanceof ApiError ? e.detail : String(e);
      confirming = false;
    } finally {
      saving = false;
    }
  }
</script>

<div class="screen entry">
  <div class="top">
    <h1>{t("score.title")}</h1>
    <span class="spacer"></span>
    <button onclick={() => flow.go({ name: "player", playerId })}>{t("common.back")}</button>
  </div>

  {#if done}
    <div class="done">
      <div class="check">✓</div>
      <h2>{t("score.saved")}</h2>
      <p class="num gold">{num(score, lang())}</p>
    </div>
  {:else}
    <p class="muted hint">{t("score.hint")}</p>
    <div class="cols">
      <div class="fields">
        <button class="val" class:on={field === "score"} onclick={() => (field = "score")}>
          <span class="label">{t("score.score")}</span>
          <span class="num big">{values.score ? num(score, lang()) : "0"}</span>
        </button>
        <div class="val" class:on={field === "level"}>
          <span class="label">{t("score.start_level")}</span>
          <div class="chips">
            {#each LEVELS as l (l)}
              <button class:sel={values.level === String(l)} onclick={() => (values.level = String(l))}>{l}</button>
            {/each}
            <button class:sel={field === "level"} onclick={() => ((field = "level"), (values.level = ""))}>…</button>
          </div>
          {#if field === "level"}<span class="num">{values.level || "–"}</span>{/if}
        </div>
        <button class="val" class:on={field === "lines"} onclick={() => (field = "lines")}>
          <span class="label">{t("score.lines")}</span>
          <span class="num">{values.lines || "–"}</span>
        </button>
        {#if error}<p class="error">{error}</p>{/if}
        <button class="primary big" disabled={!valid} onclick={() => (confirming = true)}>{t("common.next")}</button>
      </div>
      <NumPad bind:value={values[field]} maxLength={LIMITS[field]} />
    </div>
  {/if}

  {#if confirming}
    <div class="overlay">
      <div class="panel dialog">
        <h2>{t("score.confirm", { score: num(score, lang()) })}</h2>
        <p class="muted">
          {t("score.start_level")}: {level ?? "–"} · {t("score.lines")}: {values.lines || "–"}
        </p>
        <div class="row">
          <button class="big" disabled={saving} onclick={() => (confirming = false)}>{t("common.cancel")}</button>
          <button class="primary big" disabled={saving} onclick={save}>{t("common.save")}</button>
        </div>
      </div>
    </div>
  {/if}
</div>

<style>
  .entry {
    gap: 16px;
  }
  .top {
    display: flex;
    align-items: center;
    gap: 16px;
  }
  .hint {
    max-width: 1100px;
    font-size: 19px;
  }
  .cols {
    display: flex;
    gap: 50px;
    align-items: flex-start;
  }
  .fields {
    flex: 1;
    max-width: 760px;
    display: grid;
    gap: 14px;
  }
  .val {
    display: grid;
    gap: 6px;
    justify-items: start;
    padding: 14px 22px;
    min-height: 0;
    text-align: left;
    background: var(--panel);
    border: 2px solid var(--line);
    border-radius: var(--radius);
    font-size: 30px;
  }
  .val.on {
    border-color: var(--accent);
  }
  .label {
    font-size: 17px;
    color: var(--muted);
  }
  .big {
    font-size: 54px;
    color: var(--accent);
  }
  button.big {
    font-size: 30px;
    color: inherit;
  }
  button.primary.big {
    color: var(--accent-ink);
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .chips button {
    padding: 0;
    width: 76px;
    font-family: var(--mono);
    font-size: 26px;
  }
  .chips button.sel {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--accent-ink);
  }
  .done {
    flex: 1;
    display: grid;
    place-content: center;
    justify-items: center;
    gap: 16px;
  }
  .check {
    width: 140px;
    height: 140px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-size: 90px;
    background: var(--ok);
    color: #04210f;
  }
  .gold {
    color: var(--accent);
    font-size: 48px;
  }
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 40;
    display: grid;
    place-items: center;
    background: rgb(0 0 0 / 0.6);
  }
  .dialog {
    display: grid;
    gap: 22px;
    justify-items: center;
    padding: 36px 48px;
  }
</style>
