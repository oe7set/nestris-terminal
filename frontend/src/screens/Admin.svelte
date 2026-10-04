<script lang="ts">
  // Hidden admin menu (5 taps on the logo): PIN, settings, reader, updates, debug.
  import { onMount } from "svelte";
  import NumPad from "../components/NumPad.svelte";
  import TextField from "../components/TextField.svelte";
  import UpdatesPanel from "../components/UpdatesPanel.svelte";
  import { api, ApiError, setAdminToken } from "../lib/api";
  import { bridge } from "../lib/bridge.svelte";
  import { flow } from "../lib/flow.svelte";
  import { t } from "../lib/i18n.svelte";

  interface Config {
    host_url: string;
    has_token: boolean;
    rfid_driver: string;
    rfid_port: string;
    lang: string;
    fullscreen: boolean;
    hide_cursor: boolean;
    idle_timeout_s: number;
    card_grace_s: number;
    default_pin: boolean;
    config_file: string;
  }
  interface Port {
    device: string;
    description: string;
    likely_reader: boolean;
  }
  interface LogEntry {
    id: number;
    ts: string;
    level: string;
    message: string;
  }

  let unlocked = $state(false);
  let pin = $state("");
  let pinError = $state(false);
  let tab = $state<"settings" | "reader" | "updates" | "debug">("settings");
  let message = $state<{ ok: boolean; text: string } | null>(null);

  // settings
  let config = $state<Config | null>(null);
  let ports = $state<Port[]>([]);
  let hostUrl = $state("");
  let hostToken = $state("");
  let driver = $state("serial");
  let port = $state("");
  let language = $state("de");
  let fullscreen = $state(true);
  let hideCursor = $state(false);
  let idle = $state("120");
  let grace = $state("3");
  let newPin = $state("");

  // reader (settings stored in the reader itself)
  interface ReaderSnapshot {
    ready: boolean;
    port: string | null;
    info: {
      fw: string | null;
      serial: string | null;
      display: string | null;
      chip: string | null;
      reader_ok: boolean | null;
      protocol_error: string | null;
    };
  }
  let reader = $state<ReaderSnapshot | null>(null);
  let readerDisplay = $state("128x32");
  let readerFlip = $state(false);
  let readerBrightness = $state("200");

  // debug
  let debug = $state<Record<string, unknown> | null>(null);
  let logs = $state<LogEntry[]>([]);
  let hostTest = $state<string | null>(null);
  let fakeUid = $state("04A1B2C3D4");
  let fakeName = $state("");

  function fail(e: unknown): void {
    if (e instanceof ApiError && e.status === 401) {
      unlocked = false; // token expired
      setAdminToken(null);
    }
    message = { ok: false, text: e instanceof ApiError ? e.detail : String(e) };
  }

  async function unlock(): Promise<void> {
    pinError = false;
    try {
      const r = await api<{ token: string }>("/local/admin/unlock", { method: "POST", body: { pin } });
      setAdminToken(r.token);
      unlocked = true;
      pin = "";
      await loadConfig();
    } catch {
      pinError = true;
      pin = "";
    }
  }

  async function loadConfig(): Promise<void> {
    try {
      const c = await api<Config>("/local/admin/config");
      config = c;
      hostUrl = c.host_url;
      driver = c.rfid_driver;
      port = c.rfid_port;
      language = c.lang;
      fullscreen = c.fullscreen;
      hideCursor = c.hide_cursor;
      idle = String(c.idle_timeout_s);
      grace = String(c.card_grace_s);
      ports = await api<Port[]>("/local/admin/ports");
    } catch (e) {
      fail(e);
    }
  }

  async function save(): Promise<void> {
    message = null;
    try {
      await api("/local/admin/config", {
        method: "PUT",
        body: {
          host_url: hostUrl.trim(),
          host_token: hostToken.trim() || null,
          rfid_driver: driver,
          rfid_port: port,
          lang: language,
          fullscreen,
          hide_cursor: hideCursor,
          idle_timeout_s: Number(idle) || 120,
          card_grace_s: Number(grace) || 3,
          new_pin: newPin || null,
        },
      });
      hostToken = "";
      newPin = "";
      message = { ok: true, text: t("admin.saved") };
      await loadConfig();
    } catch (e) {
      fail(e);
    }
  }

  async function loadReader(): Promise<void> {
    try {
      reader = await api<ReaderSnapshot>("/local/admin/reader");
      if (reader.info.display) readerDisplay = reader.info.display;
    } catch (e) {
      fail(e);
    }
  }

  async function saveReader(): Promise<void> {
    message = null;
    try {
      reader = await api<ReaderSnapshot>("/local/admin/reader", {
        method: "PUT",
        body: {
          display: readerDisplay,
          flip: readerFlip,
          brightness: Math.min(255, Math.max(0, Number(readerBrightness) || 0)),
          lang: bridge.kiosk.lang,
        },
      });
      message = { ok: true, text: t("admin.reader_saved") };
      setTimeout(() => void loadReader(), 500);  // the reader answers with a fresh hello
    } catch (e) {
      fail(e);
    }
  }

  async function testHost(): Promise<void> {
    hostTest = "…";
    try {
      const r = await api<{ ok: boolean; ms?: number; status?: number; detail?: string }>("/local/admin/test-host", {
        method: "POST",
      });
      hostTest = r.ok ? `OK · ${r.ms} ms` : `✕ ${r.status ?? ""} ${r.detail ?? ""}`;
    } catch (e) {
      fail(e);
      hostTest = null;
    }
  }

  async function fake(action: "place" | "remove"): Promise<void> {
    try {
      await api("/local/admin/fake-card", {
        method: "POST",
        body: { action, uid: fakeUid.trim() || "04A1B2C3D4", name: fakeName.trim() || null },
      });
    } catch (e) {
      fail(e);
    }
  }

  async function refreshDebug(): Promise<void> {
    if (!unlocked || tab !== "debug") return;
    try {
      debug = await api<Record<string, unknown>>("/local/admin/debug");
      const after = logs.length ? logs[logs.length - 1]!.id : 0;
      const r = await api<{ entries: LogEntry[] }>("/local/admin/logs", { query: { after_id: String(after) } });
      logs = [...logs, ...r.entries].slice(-200);
    } catch (e) {
      fail(e);
    }
  }

  // Two taps instead of a native confirm() dialog.
  let quitArmed = $state(false);
  async function quit(): Promise<void> {
    if (!quitArmed) {
      quitArmed = true;
      setTimeout(() => (quitArmed = false), 4000);
      return;
    }
    try {
      await api("/local/admin/quit", { method: "POST" });
    } catch (e) {
      fail(e);
    }
  }

  function close(): void {
    setAdminToken(null);
    flow.menu();
  }

  onMount(() => {
    const id = setInterval(() => void refreshDebug(), 2000);
    return () => {
      clearInterval(id);
      setAdminToken(null);
    };
  });

  $effect(() => {
    if (tab === "debug") void refreshDebug();
    if (tab === "reader") void loadReader();
  });

  function show(value: unknown): string {
    if (value === null || value === undefined) return "–";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }

  const debugRows = $derived.by(() => {
    if (!debug) return [];
    const d = debug as Record<string, Record<string, unknown>>;
    return [
      ["Version", debug.version],
      ["Uptime", `${debug.uptime_s} s`],
      [t("admin.reader"), `${d.reader?.connected ? "✓" : "✕"} ${d.reader?.port ?? ""} · lines ${d.reader?.lines_seen ?? 0}`],
      ["Card", d.reader?.card],
      ["Last card", d.reader?.last_card],
      ["Host", `${d.host?.reachable ? "✓" : "✕"} ${d.host?.url ?? ""} ${d.host?.error ?? ""}`],
      ["Event", (d.host?.event as { name?: string } | null)?.name],
      ["Token", d.host_detail?.has_token ? t("admin.token_set") : t("admin.token_missing")],
      ["Server", d.host_detail?.server],
      ["IP", (d.network?.addresses as string[] | undefined)?.join(", ")],
      ["WLAN", d.network?.wifi],
      ["System", `${d.system?.hostname ?? ""} · ${d.system?.platform ?? ""} · Python ${d.system?.python ?? ""}`],
      ["WS", debug.ws_clients],
    ] as [string, unknown][];
  });
</script>

<div class="screen admin">
  {#if !unlocked}
    <div class="gate">
      <h2>{t("admin.pin")}</h2>
      <div class="pin mono" class:bad={pinError}>{"•".repeat(pin.length) || " "}</div>
      {#if pinError}<p class="error">{t("admin.wrong_pin")}</p>{/if}
      <NumPad bind:value={pin} maxLength={12} onEnter={unlock} enterDisabled={pin.length < 4} enterLabel="OK" />
      <button onclick={close}>{t("common.cancel")}</button>
    </div>
  {:else}
    <div class="top">
      <div class="tabs">
        <button class:on={tab === "settings"} onclick={() => (tab = "settings")}>{t("admin.settings")}</button>
        <button class:on={tab === "reader"} onclick={() => (tab = "reader")}>{t("admin.reader_tab")}</button>
        <button class:on={tab === "updates"} onclick={() => (tab = "updates")}>{t("admin.updates")}</button>
        <button class:on={tab === "debug"} onclick={() => (tab = "debug")}>{t("admin.debug")}</button>
      </div>
      <span class="spacer"></span>
      <button class="danger" onclick={quit}>{quitArmed ? t("admin.quit_confirm") : t("admin.quit")}</button>
      <button class="primary" onclick={close}>{t("admin.close")}</button>
    </div>
    {#if message}<p class={message.ok ? "ok" : "error"}>{message.text}</p>{/if}

    <div class="body scroll">
      {#if tab === "settings" && config}
        {#if config.default_pin}<p class="warnline">⚠ {t("admin.default_pin")}</p>{/if}
        <div class="grid">
          <TextField id="host_url" label={t("admin.host_url")} bind:value={hostUrl} layout="url" maxLength={200} />
          <TextField
            id="host_token"
            label={t("admin.host_token")}
            bind:value={hostToken}
            maxLength={200}
            hint={config.has_token ? t("admin.token_set") : t("admin.token_missing")}
          />
          <div class="group">
            <span class="label">{t("admin.reader")}</span>
            <div class="chips">
              <button class:sel={driver === "serial" && port === ""} onclick={() => ((driver = "serial"), (port = ""))}>
                USB · {t("admin.port_auto")}
              </button>
              {#each ports as p (p.device)}
                <button class:sel={driver === "serial" && port === p.device} onclick={() => ((driver = "serial"), (port = p.device))}>
                  {p.device}{p.likely_reader ? " ★" : ""}
                </button>
              {/each}
              <button class:sel={driver === "fake"} onclick={() => (driver = "fake")}>{t("admin.driver_fake")}</button>
            </div>
          </div>
          <div class="group">
            <span class="label">{t("admin.lang")}</span>
            <div class="chips">
              <button class:sel={language === "de"} onclick={() => (language = "de")}>Deutsch</button>
              <button class:sel={language === "en"} onclick={() => (language = "en")}>English</button>
            </div>
          </div>
          <div class="group">
            <div class="chips">
              <button class:sel={fullscreen} onclick={() => (fullscreen = !fullscreen)}>{fullscreen ? "✓" : "✕"} {t("admin.fullscreen")}</button>
              <button class:sel={hideCursor} onclick={() => (hideCursor = !hideCursor)}>{hideCursor ? "✓" : "✕"} {t("admin.hide_cursor")}</button>
            </div>
          </div>
          <div class="two">
            <TextField id="idle" label={t("admin.idle")} bind:value={idle} layout="number" maxLength={4} />
            <TextField id="grace" label={t("admin.grace")} bind:value={grace} layout="number" maxLength={3} />
          </div>
          <TextField id="new_pin" label={t("admin.new_pin")} bind:value={newPin} layout="number" maxLength={12} secret />
          <p class="muted small">{config.config_file}</p>
          <button class="primary big" onclick={save}>{t("common.save")}</button>
        </div>
      {:else if tab === "reader"}
        <div class="grid">
          {#if reader}
            {#if reader.info.protocol_error}
              <p class="warnline">⚠ {reader.info.protocol_error}</p>
            {:else if !reader.ready}
              <p class="warnline">⚠ {t("admin.reader_not_ready")}</p>
            {/if}
            <table>
              <tbody>
                <tr><th>{t("admin.reader_fw")}</th><td class="mono">{reader.info.fw ?? "–"}</td></tr>
                <tr><th>{t("admin.reader_serial")}</th><td class="mono">{reader.info.serial ?? "–"}</td></tr>
                <tr><th>Port</th><td class="mono">{reader.port ?? "–"}</td></tr>
                <tr><th>RC522</th><td class="mono">{reader.info.chip ?? "–"} {reader.info.reader_ok === false ? "✕" : "✓"}</td></tr>
                <tr><th>{t("admin.reader_display")}</th><td class="mono">{reader.info.display ?? "–"}</td></tr>
              </tbody>
            </table>
          {/if}
          <div class="group">
            <span class="label">{t("admin.reader_display")}</span>
            <div class="chips">
              {#each ["128x32", "128x64", "none"] as d (d)}
                <button class:sel={readerDisplay === d} onclick={() => (readerDisplay = d)}>{d === "none" ? t("admin.reader_no_display") : d}</button>
              {/each}
              <button class:sel={readerFlip} onclick={() => (readerFlip = !readerFlip)}>{readerFlip ? "✓" : "✕"} {t("admin.reader_flip")}</button>
            </div>
          </div>
          <TextField id="reader_brightness" label={t("admin.reader_brightness")} bind:value={readerBrightness} layout="number" maxLength={3} />
          <p class="muted small">{t("admin.reader_hint")}</p>
          <button class="primary big" disabled={!reader?.ready} onclick={saveReader}>{t("admin.reader_save")}</button>
        </div>
      {:else if tab === "updates"}
        <UpdatesPanel onError={fail} />
      {:else if tab === "debug"}
        <div class="debug">
          <div class="panel">
            <table>
              <tbody>
                {#each debugRows as [k, v] (k)}
                  <tr><th>{k}</th><td class="mono">{show(v)}</td></tr>
                {/each}
              </tbody>
            </table>
            <div class="row">
              <button onclick={testHost}>{t("admin.test_host")}</button>
              {#if hostTest}<span class="mono">{hostTest}</span>{/if}
            </div>
          </div>
          <div class="panel">
            <h3>{t("admin.fake")}</h3>
            <div class="two">
              <TextField id="fake_uid" label="UID" bind:value={fakeUid} maxLength={20} />
              <TextField id="fake_name" label="Name" bind:value={fakeName} maxLength={15} />
            </div>
            <div class="row">
              <button onclick={() => fake("place")}>{t("admin.fake_place")}</button>
              <button onclick={() => fake("remove")}>{t("admin.fake_remove")}</button>
            </div>
          </div>
          <div class="panel logs">
            <h3>{t("admin.logs")}</h3>
            <div class="loglines mono">
              {#each [...logs].reverse() as l (l.id)}
                <div class="l {l.level.toLowerCase()}">{l.message}</div>
              {/each}
            </div>
          </div>
        </div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .admin {
    gap: 14px;
  }
  .gate {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 18px;
  }
  .pin {
    min-width: 300px;
    padding: 12px 20px;
    text-align: center;
    font-size: 44px;
    letter-spacing: 0.3em;
    border: 2px solid var(--line);
    border-radius: var(--radius);
    background: #0b0b14;
  }
  .pin.bad {
    border-color: var(--bad);
  }
  .top {
    display: flex;
    gap: 14px;
    align-items: center;
  }
  .tabs {
    display: flex;
    gap: 10px;
  }
  .tabs button.on {
    border-color: var(--accent);
    color: var(--accent);
  }
  .body {
    flex: 1;
    min-height: 0;
    padding-right: 8px;
  }
  .grid {
    display: grid;
    gap: 16px;
    max-width: 1100px;
  }
  .two {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
  }
  .group {
    display: grid;
    gap: 6px;
  }
  .label {
    font-size: 18px;
    color: var(--muted);
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
  .warnline {
    color: var(--warn);
    margin-bottom: 12px;
  }
  .small {
    font-size: 16px;
  }
  .debug {
    display: grid;
    grid-template-columns: 1.3fr 1fr;
    gap: 18px;
  }
  .debug .panel {
    display: grid;
    gap: 12px;
    align-content: start;
  }
  .logs {
    grid-column: 1 / -1;
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
    vertical-align: top;
    white-space: nowrap;
  }
  td {
    padding: 4px 0;
    word-break: break-all;
  }
  .loglines {
    max-height: 340px;
    overflow-y: auto;
    font-size: 15px;
    user-select: text;
  }
  .l.warning {
    color: var(--warn);
  }
  .l.error,
  .l.critical {
    color: var(--bad);
  }
</style>
