import type { Status, Visit } from "./api";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

interface Wall {
  y: number;
  m: number; // 1-12
  d: number;
  hh: number;
  mm: number;
  ss: number;
}

// Read the wall-clock digits as written; any UTC offset or Z is ignored on purpose.
function parseWall(text: string): Wall {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/.exec(text);
  if (!m) throw new Error(`Unrecognised time: ${text}`);
  return { y: +m[1], m: +m[2], d: +m[3], hh: +m[4], mm: +m[5], ss: +(m[6] ?? 0) };
}

function wallMs(w: Wall): number {
  return Date.UTC(w.y, w.m - 1, w.d, w.hh, w.mm, w.ss);
}

function nowWall(now: Date): Wall {
  return {
    y: now.getFullYear(), m: now.getMonth() + 1, d: now.getDate(),
    hh: now.getHours(), mm: now.getMinutes(), ss: now.getSeconds(),
  };
}

const capitalise = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const pad = (n: number) => String(n).padStart(2, "0");
const clock = (w: Wall) => `${pad(w.hh)}:${pad(w.mm)}`;
const dayKey = (w: Wall) => `${w.y}-${pad(w.m)}-${pad(w.d)}`;

function dayLabel(w: Wall, today: string): "today" | "yesterday" | "older" {
  const key = dayKey(w);
  if (key === today) return "today";
  const t = /^(\d{4})-(\d{2})-(\d{2})$/.exec(today);
  if (t) {
    const yesterday = new Date(Date.UTC(+t[1], +t[2] - 1, +t[3] - 1));
    const yKey = `${yesterday.getUTCFullYear()}-${pad(yesterday.getUTCMonth() + 1)}-${pad(yesterday.getUTCDate())}`;
    if (key === yKey) return "yesterday";
  }
  return "older";
}

export function visitTime(startedAt: string, endedAt: string, today: string): string {
  const start = parseWall(startedAt);
  const minutes = Math.floor((wallMs(parseWall(endedAt)) - wallMs(start)) / 60000);
  const stay = minutes < 1 ? "stayed under 1 min" : `stayed ${minutes} min`;
  const when = dayLabel(start, today);
  const prefix =
    when === "today" ? "" : when === "yesterday" ? "Yesterday " : `${start.d} ${MONTHS[start.m - 1]} `;
  return `${prefix}${clock(start)} · ${stay}`;
}

export function durationText(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  return `${Math.floor(s / 60)}:${pad(s % 60)}`;
}

export function clipBadge(durationS: number | null, clipCount: number): string {
  const clips = `${clipCount} ${clipCount === 1 ? "clip" : "clips"}`;
  return durationS === null ? `▶ ${clips}` : `▶ ${durationText(durationS)} · ${clips}`;
}

// "09:12" from a timestamp, read as written.
export function timeOfDay(at: string): string {
  return clock(parseWall(at));
}

// "06:10", "yesterday 16:20" or "20 Oct 16:20", judged against the server's day.
export function whenText(at: string, today: string): string {
  const w = parseWall(at);
  const when = dayLabel(w, today);
  if (when === "today") return clock(w);
  if (when === "yesterday") return `yesterday ${clock(w)}`;
  return `${w.d} ${MONTHS[w.m - 1]} ${clock(w)}`;
}

export function speciesLabel(s: { name: string | null; scientific: string }): string {
  return capitalise(s.name ?? s.scientific);
}

export function sureChip(confidence: number | null): string | null {
  if (confidence === null) return null;
  return `${Math.min(99, Math.round(confidence * 100))}% sure`;
}

export function visitName(visit: Visit): string {
  if (visit.species) return capitalise(visit.species.name ?? visit.species.scientific);
  if (visit.subject === "person") return "Person";
  if (visit.subject === "nothing") return "Empty clip";
  if (visit.category === "birds") return "Unknown bird";
  if (visit.category === "other_animals") return "Unknown animal";
  return "Unknown";
}

export function cameraStatus(
  camera: Status["camera"],
  now: Date,
): { dot: "ok" | "asleep" | "problem"; text: string } {
  const dot = camera.state;
  const seen = camera.last_seen_at ? parseWall(camera.last_seen_at) : null;
  if (dot === "ok") {
    if (!seen) return { dot, text: "Camera seen just now" };
    const minutes = Math.floor((wallMs(nowWall(now)) - wallMs(seen)) / 60000);
    return { dot, text: minutes < 1 ? "Camera seen just now" : `Camera seen ${minutes} min ago` };
  }
  if (dot === "asleep") {
    return { dot, text: seen ? `Camera asleep · seen ${clock(seen)}` : "Camera asleep" };
  }
  if (!seen) return { dot, text: "Camera not seen yet · Check App status" };
  const today = dayKey(nowWall(now));
  const when = dayLabel(seen, today);
  const since =
    when === "today" ? clock(seen) : when === "yesterday" ? `yesterday ${clock(seen)}` : `${seen.d} ${MONTHS[seen.m - 1]}`;
  return { dot, text: `Camera not seen since ${since} · Check App status` };
}
