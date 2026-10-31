/** A drawn placeholder for a SAMPLE product picture (sample data only): a plain illustration with a "Sample picture" caption, as a data address, so no real image is needed and none is fetched. */
const LOOK: Record<string, { bg: string; body: string; label: string }> = {
  front: { bg: "#F4F5F2", body: "#9AA5A0", label: "front view" },
  angle: { bg: "#EEF1F4", body: "#8C9AA8", label: "angled view" },
  detail: { bg: "#F1EFEA", body: "#A59C8A", label: "close-up" },
  usage: { bg: "#3A3A36", body: "#8A8F86", label: "in use" },
};
export function sampleImageUrl(fileUrl: string): string {
  const key = fileUrl.split("/").pop() ?? "front";
  const l = LOOK[key] ?? LOOK.front;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240"><rect width="240" height="240" fill="${l.bg}"/><rect x="62" y="70" width="116" height="110" rx="14" fill="${l.body}"/><rect x="54" y="56" width="132" height="24" rx="10" fill="#6E7A75"/><text x="120" y="212" text-anchor="middle" font-family="sans-serif" font-size="12" fill="#6B7268">Sample picture · ${l.label}</text></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}
