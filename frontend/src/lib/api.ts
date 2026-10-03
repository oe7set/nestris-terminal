// Calls to the local bridge (/api -> NestrisLTM, /local -> card + admin).

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
  }
}

let adminToken: string | null = null;

export function setAdminToken(token: string | null): void {
  adminToken = token;
}

export function errorDetail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => (d as { msg?: string }).msg ?? "").join("; ");
    }
  }
  return fallback;
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; query?: Record<string, string> } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (adminToken && path.startsWith("/local/admin")) headers["X-Admin-Token"] = adminToken;
  const qs = options.query ? `?${new URLSearchParams(options.query)}` : "";
  let response: Response;
  try {
    response = await fetch(path + qs, {
      method: options.method ?? "GET",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new ApiError(0, "bridge not reachable");
  }
  const text = await response.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!response.ok) throw new ApiError(response.status, errorDetail(body, response.statusText));
  return body as T;
}

// ---------------------------------------------------------------- shapes

export interface PlayerRef {
  id: number;
  nickname: string;
}

export interface CardLookup {
  status: "known" | "name_match" | "unknown";
  uid: string;
  player?: PlayerRef;
  name?: string | null;
}

export interface Stats {
  games: number;
  best_score: number | null;
  avg_score: number | null;
  total_score: number;
  total_lines: number;
  best_level: number | null;
  tetris_rate: number | null;
  first_game: string | null;
  last_game: string | null;
}

export interface Standing {
  rank: number;
  players: number;
  best_score: number;
  best_game_id: number | null;
  next_rank_score: number | null;
  gap_to_next: number | null;
  next_rank_name: string | null;
}

export interface GameRow {
  id: number;
  started_at: string;
  status: string;
  source: string;
  station_id: string | null;
  score: number | null;
  lines: number | null;
  start_level: number | null;
  end_level: number | null;
  tetris_rate: number | null;
  replay: boolean;
}

export interface Profile {
  player: PlayerRef;
  all_time: Stats;
  current: ({ event: { id: number; name: string }; standing: Standing | null } & Stats) | null;
  events: ({ event: { id: number; name: string; starts_at: string }; active: boolean; rank: number | null; players: number | null } & Stats)[];
  games: GameRow[];
}

export interface HighscoreEntry {
  rank: number;
  user_id: number;
  nickname: string;
  score: number;
  level: number | null;
  lines: number | null;
  is_live: boolean;
  game_id: number | null;
}

export interface Highscore {
  event: { id: number; name: string } | null;
  stats: { total_games: number; active_players: number; highest_score: number };
  entries: HighscoreEntry[];
}
