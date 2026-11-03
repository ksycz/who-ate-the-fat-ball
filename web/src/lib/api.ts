export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      if (typeof data?.detail === "string") detail = data.detail;
    } catch {
      // not JSON; keep the status text
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function getJSON<T>(path: string): Promise<T> {
  return request<T>("GET", path);
}

export function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  return request<T>(method, path, body);
}

export type Category = "birds" | "other_animals" | "other";
export type CameraState = "ok" | "asleep" | "problem";

export interface SpeciesRef {
  scientific: string;
  name: string | null;
}

// One row of GET /api/species?period=: the counts are for the period, the dates are all-time.
export interface SpeciesSummary {
  scientific: string;
  name: string | null;
  visits: number;
  last_seen_at: string;
  first_seen_at: string | null;
  is_new: boolean;
  photo_url: string | null;
}

export interface Visit {
  id: number;
  started_at: string;
  ended_at: string;
  category: Category;
  species: SpeciesRef | null;
  subject: string;
  confidence: number | null;
  is_favourite: boolean;
  best_frame_url: string | null;
  clip_count: number;
  duration_s: number | null;
  poster_url: string | null;
  preview_url: string | null;
  corrected: boolean;
  watched: boolean;
}

export interface Clip {
  id: number;
  begin_at: string;
  end_at: string;
  kind: "video" | "photo" | string;
  duration_s: number | null;
  web_url: string | null;
  original_url: string | null;
  poster_url: string | null;
  preview_url: string | null;
}

export interface Guess {
  scientific: string;
  name: string | null;
  confidence: number;
}

export type VisitDetail = Visit & { clips: Clip[]; guesses: Guess[] };

export interface Camera {
  state: CameraState;
  last_seen_at: string | null;
  last_error: string | null;
}

export interface Today {
  day: string;
  now: string; // the Mac's clock when it answered, ISO with its UTC offset
  summary: { visits: number; species: number };
  champion: {
    scientific: string;
    name: string | null;
    count: number;
    first_at: string;
    best_frame_url: string | null;
  } | null;
  new_species: { visit_id: number; scientific: string; name: string | null; started_at: string } | null;
  visits: Visit[];
  checking: Clip[];
  failed: { clip_id: number; begin_at: string; can_retry: boolean }[];
  last_visitor: { name: string | null; started_at: string } | null;
  camera: Camera;
}

export interface Species {
  scientific: string;
  name: string | null;
  group: "bird" | "mammal";
  visits: number;
  last_seen_at: string | null;
}

export interface Status {
  day: string;
  now: string; // the Mac's clock when it answered, ISO with its UTC offset
  local: boolean; // the request comes from the Mac itself
  camera: Camera;
  sorted: { birds: number; other_animals: number; other: number; favourites: number };
  queue: { downloaded: number; processing: number; failed: number };
  recognition: { pending: number; old_waiting: number; errors: number; model: boolean; examples: number };
  disk: { free_bytes: number; low: boolean };
}

export interface StatsSummary {
  weeks: number;
  visits: number;
  species: number;
  busiest: string | null;
  slots: string[];
  heatmap: { day: string; cells: number[] }[];
  per_species: { scientific: string; name: string | null; visits: number }[];
}
