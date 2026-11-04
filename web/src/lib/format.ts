import type { Category, Status, Visit } from "./api";

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
  if (visit.category === "other") return "Other"; // a plain move to Other: it could be anything, so not "Empty clip"
  return "Unknown";
}

// Whole minutes from `at` to now, by the server's clock: the time it gave us (`serverNow`, read at
// `fetchedAt` by this device's clock) plus however long this device has waited since (`nowMs`).
// Only differences between two readings of the same clock are used, so a wrong browser date changes nothing.
export function minutesAgo(at: string, serverNow: string, fetchedAt: number, nowMs: number): number {
  const sinceReply = Math.max(0, nowMs - fetchedAt);
  const ms = wallMs(parseWall(serverNow)) + sinceReply - wallMs(parseWall(at));
  return Math.max(0, Math.floor(ms / 60000));
}

export interface ServerClock {
  serverNow: string;
  fetchedAt: number;
  nowMs: number;
}

export function cameraStatus(
  camera: Status["camera"],
  today: string,
  clockNow: ServerClock,
): { dot: "ok" | "asleep" | "problem"; text: string } {
  const dot = camera.state;
  const seen = camera.last_seen_at ? parseWall(camera.last_seen_at) : null;
  if (dot === "ok") {
    if (!camera.last_seen_at) return { dot, text: "Camera seen just now" };
    const minutes = minutesAgo(camera.last_seen_at, clockNow.serverNow, clockNow.fetchedAt, clockNow.nowMs);
    return { dot, text: minutes < 1 ? "Camera seen just now" : `Camera seen ${minutes} min ago` };
  }
  if (dot === "asleep") {
    if (!seen) return { dot, text: "Camera asleep" };
    const when = dayLabel(seen, today);
    if (when === "today") return { dot, text: `Camera asleep · seen ${clock(seen)}` };
    return { dot, text: `Camera asleep · since ${when === "yesterday" ? `yesterday ${clock(seen)}` : `${seen.d} ${MONTHS[seen.m - 1]}`}` };
  }
  if (!seen) return { dot, text: "Camera not seen yet · Check App status" };
  const when = dayLabel(seen, today);
  const since =
    when === "today" ? clock(seen) : when === "yesterday" ? `yesterday ${clock(seen)}` : `${seen.d} ${MONTHS[seen.m - 1]}`;
  return { dot, text: `Camera not seen since ${since} · Check App status` };
}

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

// "Today", "Yesterday" or "Saturday 31 October" for a "YYYY-MM-DD" day, judged against the server's day.
export function dayHeading(day: string, today: string): string {
  if (day === today) return "Today";
  const t = /^(\d{4})-(\d{2})-(\d{2})$/.exec(today);
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day);
  if (!d) return day;
  if (t) {
    const y = new Date(Date.UTC(+t[1], +t[2] - 1, +t[3] - 1));
    if (`${y.getUTCFullYear()}-${pad(y.getUTCMonth() + 1)}-${pad(y.getUTCDate())}` === day) return "Yesterday";
  }
  const date = new Date(Date.UTC(+d[1], +d[2] - 1, +d[3]));
  return `${WEEKDAYS[date.getUTCDay()]} ${+d[3]} ${MONTH_NAMES[+d[2] - 1]}`;
}

// The calendar day ("YYYY-MM-DD") a timestamp was written on.
export function dayOf(at: string): string {
  return dayKey(parseWall(at));
}

// The colour dot beside each category (the same as in the side menu).
export const CATEGORY_DOTS: Record<Category, string> = {
  birds: "var(--robin)",
  other_animals: "var(--dot-animals)",
  other: "var(--dot-other)",
};

export const CATEGORY_NAMES: Record<Category, string> = {
  birds: "Birds",
  other_animals: "Other animals",
  other: "Other",
};

// The toast after a correction: it says where the visit went when its list changed, else what it was changed to.
export function correctionText(from: Category, to: Category, label: string): string {
  return from !== to ? `Moved to ${CATEGORY_NAMES[to]}` : `Changed to ${label}`;
}

// "1 visit", "2 visits".
export const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? "" : "s"}`;

// "820 KB", "14.2 MB", "1.3 GB": a file size in words, decimal units like Finder (1 decimal from 1 MB).
// The unit is picked after rounding, so 999,999 bytes is "1.0 MB", not "1000 KB".
export function sizeText(bytes: number): string {
  const kb = Math.ceil(bytes / 1e3);
  if (kb < 1000) return `${Math.max(0, kb)} KB`;
  const mb = (bytes / 1e6).toFixed(1);
  if (Number(mb) < 1000) return `${mb} MB`;
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

// 0 for no visits, else 1-4 by share of the busiest cell.
export function heatLevel(n: number, max: number): 0 | 1 | 2 | 3 | 4 {
  if (n <= 0 || max <= 0) return 0;
  return Math.min(4, Math.max(1, Math.ceil((4 * n) / max))) as 1 | 2 | 3 | 4;
}

// "Tue 8–10 am · 12 visits", from the server's day and slot labels.
export const cellText = (day: string, slot: string, n: number): string => `${day} ${slot} · ${plural(n, "visit")}`;
