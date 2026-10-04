<script lang="ts">
  // Hidden menu → Updates: terminal app and reader firmware from GitHub releases
  // (bridge: /local/admin/updates*, nestris_terminal/updates/service.py).
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import { t, lang } from "../lib/i18n.svelte";

  interface ReleaseInfo {
    version: string;
    prerelease: boolean;
    published_at: string | null;
    notes: string;
    url: string;
    is_current?: boolean;
    is_downgrade?: boolean;
  }
  interface TargetState {
    current: string | null;
    latest: ReleaseInfo | null;
    update_available: boolean;
    check_error: string | null;
    source: string;
    can_install: boolean;
    port?: string | null;
    fake?: boolean;
    old_protocol?: boolean;
  }
  interface UpdateState {
    app: TargetState;
    reader: TargetState;
    last_check: string | null;
    status: string;
    status_target: "app" | "reader" | null;
    status_detail: string | null;
    progress: number | null;
    enabled: boolean;
    channel: "stable" | "beta";
  }
  type Target = "app" | "reader";

  let { onError }: { onError: (e: unknown) => void } = $props();

  let info = $state<UpdateState | null>(null);
  let checking = $state(false);
  let others = $state<Record<Target, ReleaseInfo[] | null>>({ app: null, reader: null });
  // Two taps instead of a confirm dialog: the armed button's key.
  let armed = $state<string | null>(null);
  let armTimer: ReturnType<typeof setTimeout> | undefined;

  const BUSY = ["downloading", "verifying", "flashing", "waiting", "installing"];
  const busy = $derived(info !== null && BUSY.includes(info.status));

  async function load(): Promise<void> {
    try {
      info = await api<UpdateState>("/local/admin/updates");
    } catch (e) {
      onError(e);
    }
  }

  async function check(): Promise<void> {
    checking = true;
    try {
      info = await api<UpdateState>("/local/admin/updates/check", { method: "POST" });
      others = { app: null, reader: null };
    } catch (e) {
      onError(e);
    } finally {
      checking = false;
    }
  }

  async function setSettings(body: { channel?: string; enabled?: boolean }): Promise<void> {
    try {
      info = await api<UpdateState>("/local/admin/updates/settings", { method: "PUT", body });
      others = { app: null, reader: null };
    } catch (e) {
      onError(e);
    }
  }

  async function showOthers(target: Target): Promise<void> {
    if (others[target]) {
      others[target] = null;
      return;
    }
    try {
      others[target] = await api<ReleaseInfo[]>("/local/admin/updates/releases", { query: { target } });
    } catch (e) {
      onError(e);
    }
  }

  async function install(target: Target, version: string, mode: "app" | "factory" = "app"): Promise<void> {
    const key = `${target}:${version}:${mode}`;
    if (armed !== key) {
      armed = key;
      clearTimeout(armTimer);
      armTimer = setTimeout(() => (armed = null), 4000);
      return;
    }
    armed = null;
    try {
      info = await api<UpdateState>("/local/admin/updates/install", {
        method: "POST",
        body: { target, version, mode },
      });
    } catch (e) {
      onError(e);
      await load();
    }
  }

  function label(key: string, text: string): string {
    return armed === key ? t("upd.confirm") : text;
  }

  function when(iso: string | null): string {
    if (!iso) return t("upd.never");
    const d = new Date(iso);
    return t("upd.last_check", {
      time: d.toLocaleString(lang() === "en" ? "en-GB" : "de-AT", { dateStyle: "short", timeStyle: "short" }),
    });
  }

  const statusText = $derived.by(() => {
    if (!info || info.status === "idle") return null;
    const key = `upd.status.${info.status}` as Parameters<typeof t>[0];
    return t(key, { detail: info.status_detail ?? "" });
  });

  onMount(() => {
    void load();
    // Poll fast while something runs, slowly otherwise (reader plugged in/out).
    let stopped = false;
    async function loop(): Promise<void> {
      while (!stopped) {
        await new Promise((r) => setTimeout(r, busy ? 700 : 3000));
        if (!stopped) await load();
      }
    }
    void loop();
    return () => {
      stopped = true;
      clearTimeout(armTimer);
    };
  });
</script>

{#if info}
  <div class="updates">
    <div class="row">
      <button class="primary" disabled={checking || busy} onclick={check}>
        {checking ? t("upd.checking") : t("upd.check")}
      </button>
      <span class="muted">{when(info.last_check)}</span>
      <span class="spacer"></span>
      <div class="chips">
        <button class:sel={info.channel === "stable"} onclick={() => setSettings({ channel: "stable" })}>{t("upd.channel_stable")}</button>
        <button class:sel={info.channel === "beta"} onclick={() => setSettings({ channel: "beta" })}>{t("upd.channel_beta")}</button>
        <button class:sel={info.enabled} onclick={() => setSettings({ enabled: !info!.enabled })}>
          {info.enabled ? "✓" : "✕"} {t("upd.auto")}
        </button>
      </div>
    </div>

    {#if statusText}
      <div class="status" class:error={info.status === "error"} class:ok={info.status === "done"}>
        <span>{statusText}</span>
        {#if busy && info.progress !== null}
          <div class="bar"><div style="width: {Math.round(info.progress * 100)}%"></div></div>
        {/if}
      </div>
    {/if}

    {#each [["app", info.app], ["reader", info.reader]] as const as [target, s] (target)}
      <section class="panel">
        <h3>{target === "app" ? t("upd.app") : t("upd.reader")}</h3>
        <table>
          <tbody>
            <tr><th>{t("upd.installed")}</th><td class="mono">{s.current ?? "–"}{target === "reader" && s.port ? ` · ${s.port}` : ""}</td></tr>
            <tr>
              <th>{t("upd.available")}</th>
              <td class="mono">
                {#if s.latest}
                  {s.latest.version}{s.latest.prerelease ? " (beta)" : ""}
                  {#if !s.update_available && s.current && !s.fake}<span class="ok"> · {t("upd.up_to_date")}</span>{/if}
                {:else}
                  {t("upd.none")}
                {/if}
              </td>
            </tr>
            <tr><th>GitHub</th><td class="mono small">{s.source}</td></tr>
          </tbody>
        </table>
        {#if s.check_error}<p class="warnline">⚠ {s.check_error}</p>{/if}

        {#if target === "app"}
          {#if !s.can_install}
            <p class="muted small">{t("upd.app_dev")}</p>
          {:else if s.update_available && s.latest}
            <p class="muted small">{t("upd.app_restart")}</p>
          {/if}
        {:else if s.fake}
          <p class="muted small">{t("upd.reader_fake")}</p>
        {:else if !s.port}
          <p class="muted small">{t("upd.reader_none")}</p>
        {:else}
          <p class="muted small">{t("upd.reader_hint")}</p>
        {/if}

        {#if s.latest?.notes && s.update_available}
          <pre class="notes">{s.latest.notes}</pre>
        {/if}

        <div class="row">
          {#if s.latest && s.update_available}
            {@const key = `${target}:${s.latest.version}:app`}
            <button class="primary" disabled={!s.can_install || busy} onclick={() => install(target, s.latest!.version)}>
              {label(key, t(target === "app" ? "upd.install" : "upd.flash", { v: s.latest.version }))}
            </button>
          {/if}
          {#if target === "reader" && s.latest && s.can_install && (s.old_protocol || !s.current)}
            {@const key = `reader:${s.latest.version}:factory`}
            <button class="danger" disabled={busy} onclick={() => install("reader", s.latest!.version, "factory")}>
              {label(key, t("upd.factory", { v: s.latest.version }))}
            </button>
          {/if}
          <button disabled={busy} onclick={() => showOthers(target)}>{t("upd.other")}</button>
        </div>
        {#if target === "reader" && s.can_install && (s.old_protocol || !s.current)}
          <p class="muted small">{t("upd.factory_hint")}</p>
        {/if}

        {#if others[target]}
          <div class="chips">
            {#each others[target]! as r (r.version)}
              {@const key = `${target}:${r.version}:app`}
              <button
                disabled={r.is_current || !s.can_install || busy}
                class:sel={r.is_current}
                onclick={() => install(target, r.version)}
              >
                {label(key, r.version)}{r.prerelease ? " β" : ""}{r.is_current ? ` · ${t("upd.current")}` : ""}{r.is_downgrade ? ` · ${t("upd.downgrade")}` : ""}
              </button>
            {/each}
          </div>
        {/if}
      </section>
    {/each}
  </div>
{/if}

<style>
  .updates {
    display: grid;
    gap: 16px;
    max-width: 1100px;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    align-items: center;
  }
  .spacer {
    flex: 1;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }
  .chips button.sel {
    border-color: var(--accent);
    color: var(--accent);
  }
  .panel {
    display: grid;
    gap: 10px;
    padding: 16px;
    border: 2px solid var(--line);
    border-radius: var(--radius);
  }
  h3 {
    margin: 0;
  }
  table {
    border-collapse: collapse;
    font-size: 17px;
    justify-self: start;
  }
  th {
    text-align: left;
    color: var(--muted);
    font-weight: 400;
    padding: 4px 18px 4px 0;
  }
  td {
    padding: 4px 0;
  }
  .small {
    font-size: 16px;
  }
  .warnline {
    color: var(--warn);
  }
  .ok {
    color: var(--ok);
  }
  .status {
    display: grid;
    gap: 8px;
    padding: 12px 16px;
    border-radius: var(--radius);
    background: var(--panel);
    font-size: 19px;
  }
  .status.error {
    color: var(--bad);
  }
  .bar {
    height: 14px;
    border-radius: 7px;
    background: #0b0b14;
    overflow: hidden;
  }
  .bar div {
    height: 100%;
    background: var(--accent);
    transition: width 0.4s;
  }
  .notes {
    max-height: 180px;
    overflow-y: auto;
    margin: 0;
    padding: 10px 12px;
    background: #0b0b14;
    border-radius: var(--radius);
    font-size: 15px;
    white-space: pre-wrap;
    user-select: text;
  }
</style>
