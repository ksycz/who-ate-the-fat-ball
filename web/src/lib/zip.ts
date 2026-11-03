import { send } from "./api";

export type ZipRequest =
  | { visit_ids: number[] }
  | { day: string; category?: string; favourite?: true };

export interface ZipPlan {
  token: string;
  size_bytes: number;
  visits: number;
  filename: string;
}

// Ask the Mac to plan a .zip; it answers with how big it is. Nothing downloads yet.
export function askZip(body: ZipRequest): Promise<ZipPlan> {
  return send<ZipPlan>("POST", "/api/downloads/zip", body);
}

// Start the browser's own download by clicking a temporary link.
export function startDownload(token: string, filename: string): void {
  const a = document.createElement("a");
  a.href = `/api/downloads/zip/${encodeURIComponent(token)}`;
  a.download = filename;
  a.style.display = "none";
  document.body.appendChild(a);
  a.click();
  a.remove();
}
