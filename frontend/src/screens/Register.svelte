<script lang="ts">
  // Guided sign-up: details -> place card -> create player + link card ->
  // write the nickname onto the card -> "please remove the card" -> welcome.
  import { onMount } from "svelte";
  import TextField from "../components/TextField.svelte";
  import { api, ApiError, type CardLookup, type PlayerRef } from "../lib/api";
  import { bridge, type CardInfo } from "../lib/bridge.svelte";
  import { flow } from "../lib/flow.svelte";
  import { EMAIL_RE, NICKNAME_RE } from "../lib/format";
  import { t } from "../lib/i18n.svelte";

  let { card: initialCard }: { card: CardInfo | null } = $props();

  type Step = "data" | "card" | "checking" | "taken" | "saving" | "writing" | "write_error" | "remove" | "done";
  let step = $state<Step>("data");

  let nickname = $state("");
  let firstName = $state("");
  let lastName = $state("");
  let email = $state("");
  let consent = $state(false);

  let nickStatus = $state<"idle" | "checking" | "ok" | "taken">("idle");
  let nickError = $state<string | null>(null);
  let takenBy = $state("");
  let writeError = $state("");
  let player = $state<PlayerRef | null>(null);

  const cleanNick = $derived(nickname.trim().replace(/\s+/g, " "));
  const nickValid = $derived(NICKNAME_RE.test(cleanNick));
  const emailValid = $derived(email.trim() === "" || EMAIL_RE.test(email.trim()));
  const canContinue = $derived(nickValid && nickStatus === "ok" && emailValid);

  // ------------------------------------------------ nickname availability
  let checkTimer: ReturnType<typeof setTimeout> | null = null;
  let checkSeq = 0;
  $effect(() => {
    const value = cleanNick;
    nickError = null;
    if (checkTimer) clearTimeout(checkTimer);
    if (!value) {
      nickStatus = "idle";
      return;
    }
    if (!NICKNAME_RE.test(value)) {
      nickStatus = "idle";
      if (value.length >= 2) nickError = t("reg.invalid");
      return;
    }
    nickStatus = "checking";
    const seq = ++checkSeq;
    checkTimer = setTimeout(async () => {
      try {
        const r = await api<{ available: boolean; valid: boolean }>("/api/nickname", { query: { value } });
        if (seq !== checkSeq) return;
        nickStatus = r.available ? "ok" : "taken";
        if (!r.available) nickError = r.valid ? t("reg.taken") : t("reg.invalid");
      } catch {
        if (seq === checkSeq) {
          nickStatus = "idle";
          nickError = t("error.host");
        }
      }
    }, 350);
  });

  // ------------------------------------------------ card handling
  function toCardStep(): void {
    if (!canContinue) return;
    step = "card";
    if (bridge.card) void check(bridge.card);
  }

  async function check(card: CardInfo): Promise<void> {
    if (step !== "card") return;
    step = "checking";
    try {
      const found = await api<CardLookup>(`/api/card/${encodeURIComponent(card.uid)}`, {
        query: card.name ? { name: card.name } : undefined,
      });
      if (found.status !== "unknown" && found.player) {
        takenBy = found.player.nickname;
        step = bridge.card ? "taken" : "card";
        return;
      }
      await submit(card);
    } catch (e) {
      step = "card";
      flow.notice = { kind: "error", key: "error.host", detail: e instanceof Error ? e.message : String(e) };
    }
  }

  async function submit(card: CardInfo): Promise<void> {
    step = "saving";
    try {
      const r = await api<{ player: PlayerRef }>("/api/players", {
        method: "POST",
        body: {
          nickname: cleanNick,
          first_name: firstName.trim() || null,
          last_name: lastName.trim() || null,
          email: email.trim() || null,
          email_consent: consent && email.trim() !== "",
          card_uid: card.uid,
        },
      });
      player = r.player;
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && e.detail.includes("nickname")) {
        step = "data";
        nickStatus = "taken";
        nickError = t("reg.taken");
      } else if (e instanceof ApiError && e.status === 409) {
        takenBy = "?";
        step = bridge.card ? "taken" : "card";
      } else {
        step = "card";
        flow.notice = { kind: "error", key: "error.host", detail: e instanceof Error ? e.message : String(e) };
      }
      return;
    }
    await write();
  }

  async function write(): Promise<void> {
    if (!player) return;
    step = "writing";
    try {
      await api("/local/card/write", { method: "POST", body: { name: player.nickname } });
      step = bridge.card ? "remove" : "done";
    } catch (e) {
      writeError = e instanceof ApiError ? e.detail : String(e);
      step = "write_error";
    }
  }

  onMount(() => {
    const off = bridge.on((e) => {
      if (e.type !== "card") return;
      flow.touch();
      if (e.state === "present") {
        if (step === "card") void check({ uid: e.uid as string, name: (e.name as string) ?? null });
      } else if (step === "taken") {
        step = "card";
      } else if (step === "remove") {
        step = "done";
      }
    });
    return off;
  });

  // The welcome screen returns to the menu by itself.
  $effect(() => {
    if (step !== "done") return;
    const id = setTimeout(() => flow.menu(), 8000);
    return () => clearTimeout(id);
  });

  const stepIndex = $derived(step === "data" ? 0 : step === "done" ? 2 : 1);
</script>

<div class="screen register">
  <div class="top">
    <h1>{t("reg.title")}</h1>
    <ol class="steps">
      {#each [t("reg.step_data"), t("reg.step_card"), t("reg.step_done")] as label, i (i)}
        <li class:on={i === stepIndex} class:past={i < stepIndex}><span>{i + 1}</span>{label}</li>
      {/each}
    </ol>
    <span class="spacer"></span>
    {#if !player}
      <button onclick={() => flow.menu()}>{t("common.cancel")}</button>
    {/if}
  </div>

  {#if step === "data"}
    {#if initialCard}<p class="banner">💳 {t("reg.blank_card")}</p>{/if}
    <div class="form scroll">
      <TextField
        id="nickname"
        label={t("reg.nickname")}
        bind:value={nickname}
        maxLength={15}
        autofocus
        hint={t("reg.nickname_hint")}
        error={nickError}
        ok={nickStatus === "ok" ? t("reg.available") : null}
      />
      <div class="two">
        <TextField id="first" label={t("reg.first_name")} bind:value={firstName} maxLength={64} />
        <TextField id="last" label={t("reg.last_name")} bind:value={lastName} maxLength={64} />
      </div>
      <TextField
        id="email"
        label={t("reg.email")}
        bind:value={email}
        layout="email"
        maxLength={120}
        error={emailValid ? null : t("reg.email_invalid")}
      />
      {#if email.trim()}
        <button class="consent" class:on={consent} onclick={() => (consent = !consent)}>
          <span class="box">{consent ? "✓" : ""}</span>
          <span>{t("reg.consent")}</span>
        </button>
      {/if}
      <div class="row">
        <p class="muted small">{t("reg.privacy")}</p>
        <span class="spacer"></span>
        <button class="primary big" disabled={!canContinue} onclick={toCardStep}>{t("common.next")} →</button>
      </div>
    </div>
  {:else}
    <div class="stage">
      {#if step === "card"}
        <div class="card-anim" aria-hidden="true"><div class="reader"></div><div class="card"></div></div>
        <h2>{t("reg.place_card")}</h2>
        <button class="ghost" onclick={() => (step = "data")}>← {t("common.back")}</button>
      {:else if step === "checking"}
        <div class="spinner"></div>
        <h2>{t("reg.checking")}</h2>
      {:else if step === "taken"}
        <div class="icon bad">✕</div>
        <h2 class="error">{t("reg.card_taken", { name: takenBy })}</h2>
      {:else if step === "saving"}
        <div class="spinner"></div>
        <h2>{t("reg.saving")}</h2>
      {:else if step === "writing"}
        <div class="spinner"></div>
        <h2>{t("reg.writing")}</h2>
      {:else if step === "write_error"}
        <div class="icon warn">!</div>
        <h2>{t("reg.write_failed", { detail: writeError })}</h2>
        <div class="row">
          <button class="primary big" onclick={write}>{t("common.retry")}</button>
          <button class="big" onclick={() => (step = bridge.card ? "remove" : "done")}>{t("reg.skip_write")}</button>
        </div>
        <p class="muted">{t("reg.skip_hint")}</p>
      {:else if step === "remove"}
        <div class="card-anim out" aria-hidden="true"><div class="reader"></div><div class="card"></div></div>
        <h2 class="ok">{t("reg.remove_card")}</h2>
      {:else if step === "done"}
        <div class="icon good">✓</div>
        <h1 class="welcome">{t("reg.welcome", { name: player?.nickname ?? cleanNick })}</h1>
        <p class="muted hint">{t("reg.welcome_hint")}</p>
        <button class="primary big" onclick={() => flow.menu()}>{t("common.ok")}</button>
      {/if}
    </div>
  {/if}
</div>

<style>
  .register {
    gap: 18px;
  }
  .top {
    display: flex;
    align-items: center;
    gap: 30px;
  }
  .steps {
    display: flex;
    gap: 22px;
    list-style: none;
    margin: 0;
    padding: 0;
    color: var(--muted);
    font-size: 20px;
  }
  .steps li {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .steps span {
    display: grid;
    place-items: center;
    width: 36px;
    height: 36px;
    border-radius: 50%;
    border: 2px solid var(--line);
    font-family: var(--mono);
  }
  .steps li.on {
    color: var(--accent);
  }
  .steps li.on span {
    border-color: var(--accent);
  }
  .steps li.past span {
    background: var(--ok);
    border-color: var(--ok);
    color: #04210f;
  }
  .banner {
    padding: 12px 20px;
    border-radius: var(--radius);
    background: rgb(79 214 255 / 0.12);
    border: 1px solid var(--cyan);
    color: var(--cyan);
  }
  .form {
    display: grid;
    gap: 16px;
    align-content: start;
    max-width: 1100px;
    padding-right: 8px;
    min-height: 0;
  }
  .two {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  .consent {
    display: flex;
    gap: 16px;
    align-items: center;
    text-align: left;
    padding: 12px 18px;
    font-size: 19px;
  }
  .consent .box {
    flex: none;
    display: grid;
    place-items: center;
    width: 44px;
    height: 44px;
    border: 2px solid var(--line);
    border-radius: 8px;
    font-size: 28px;
  }
  .consent.on .box {
    background: var(--accent);
    border-color: var(--accent);
    color: var(--accent-ink);
  }
  .small {
    font-size: 17px;
  }
  .stage {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 30px;
    text-align: center;
  }
  .stage h2 {
    max-width: 1100px;
    font-size: 40px;
  }
  .welcome {
    color: var(--accent);
    font-size: 60px;
  }
  .hint {
    max-width: 900px;
  }
  .icon {
    width: 150px;
    height: 150px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-size: 90px;
    font-weight: 700;
  }
  .icon.good {
    background: var(--ok);
    color: #04210f;
    animation: pop 0.4s ease-out;
  }
  .icon.bad {
    background: var(--bad);
    color: #2a0006;
  }
  .icon.warn {
    background: var(--warn);
    color: #2a1600;
  }
  .spinner {
    width: 110px;
    height: 110px;
    border: 9px solid var(--line);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.9s linear infinite;
  }
  .card-anim {
    position: relative;
    width: 300px;
    height: 260px;
  }
  .reader {
    position: absolute;
    left: 20px;
    right: 20px;
    bottom: 0;
    height: 80px;
    border-radius: 18px;
    background: linear-gradient(#2a2a40, #15151f);
    border: 2px solid var(--line);
    box-shadow: 0 0 50px rgb(79 214 255 / 0.3);
  }
  .card {
    position: absolute;
    left: 65px;
    width: 170px;
    height: 108px;
    border-radius: 12px;
    background: linear-gradient(135deg, #f4f4fa, #b9b9cc);
    animation: place 2.4s ease-in-out infinite;
  }
  .out .card {
    background: linear-gradient(135deg, var(--accent), #ff7a3d);
    animation: lift 2.4s ease-in-out infinite;
  }
  @keyframes place {
    0%,
    100% {
      top: 0;
      transform: rotate(-8deg);
    }
    45%,
    70% {
      top: 128px;
      transform: rotate(0);
    }
  }
  @keyframes lift {
    0%,
    25% {
      top: 128px;
      transform: rotate(0);
      opacity: 1;
    }
    80% {
      top: -10px;
      transform: rotate(8deg);
      opacity: 0.2;
    }
    100% {
      top: -10px;
      opacity: 0;
    }
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  @keyframes pop {
    from {
      transform: scale(0.3);
    }
  }
</style>
