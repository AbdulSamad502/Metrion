/** CMO 3.0 M9: the Product Image Quality Advisor. Every score, finding and sentence arrives from the backend (deterministic image measurements over the seller's own images; no AI model, not even the
 * vision model). This module only types them and calls the routes. Nothing here measures, scores or judges an image, and no call uses an AI credit or publishes anything. */

import { API_BASE, ApiError, apiFetch, apiFetchForm } from "@/lib/api";
import { demoActive } from "@/lib/demo/mode";
import { sampleImageUrl } from "@/lib/demo/sampleImage";

type GetToken = () => Promise<string | null>;
const BASE = "/api/v1/cmo/product-images";
export const IMAGES_PAGE = "/dashboard/cmo/images"; // the page that holds the upload; linked by constant so the read-only showcase page carries no CMO route text

export type Marketplace = "AMAZON" | "FLIPKART" | "MEESHO";
export type Severity = "HIGH" | "MEDIUM" | "LOW";
export type Role = "PRIMARY" | "SECONDARY";
export type ShotType = { key: string; label: string };
export type ImageProduct = { sku: string; name: string; sets: { marketplace: Marketplace; images: number }[] };
export type ImageProducts = { products: ImageProduct[]; marketplaces: Marketplace[]; shotTypes: ShotType[]; limits: { maxImages: number; maxFilesPerRequest: number } };

export type StoredImage = { assetId: string; role: Role; shotType: string; position: number; widthPx: number | null; heightPx: number | null; sha256: string; fileUrl: string; assignedAt: string };
export type Finding = {
  imageNumber: number | null; imageId: string | null; role: Role | null; shotType: string | null; code: string; severity: Severity; problem: string; whyItMatters: string; recommendation: string;
  evidence: Record<string, number | string>; isMarketplaceRequirement: false;
};
export type Dimension = { key: string; label: string; max: number; state: "ASSESSED" | "PARTIAL" | "NOT_ASSESSED"; earned: number | null; assessableMax: number; percent: number | null; reason: string | null };
export type ReportImage = { imageNumber: number; imageId: string; role: Role; shotType: string; widthPx: number; heightPx: number; dimensions: Record<string, number | null>; notAssessed: Record<string, string>; overlayCheck: string; overlayCheckConfidence: "LOW" };
export type Report = {
  method: string; scoreState: "COMPLETE" | "PARTIAL" | "NOT_CALCULABLE"; score: number | null; maxScore: 100; pointsEarned: number | null; pointsAssessable: number | null; dimensions: Dimension[]; images: ReportImage[];
  duplicateCheck?: { state: "CHECKED" | "NOT_ASSESSED"; reason: string | null; pairs: { images: [number, number]; verdict: "REPEAT" | "NOT_ASSESSED"; hashDistanceOf64: number; colourDifference: number; sameKindOfShot: boolean; reason: string }[] };
  findings: Finding[]; missingShots: { code: string; shotType: string; problem: string; whyItMatters: string; recommendation: string; isMarketplaceRequirement: false }[]; notes: string[];
  product?: { sku: string; name: string }; marketplace?: Marketplace;
};
export type Compliance = {
  status: "NOT_ASSESSED" | "CHECKED_PASSED" | "CHECKED_FAILED"; marketplace: Marketplace; message: string; notAssessed: string;
  checks: { rule: string; imageNumber?: number; result: "PASS" | "FAIL"; measuredLongSidePx?: number; measuredCount?: number; source: { url: string; checkedOn: string; scope: string; value: number } }[];
};
export type ReviewHistoryRow = { id: string; createdAt: string; scoreState: string; score: number | null; imageCount: number; method: string };
export type ImagePage = {
  product: { sku: string; name: string }; marketplace: Marketplace; images: StoredImage[]; review: { reviewId: string; createdAt: string; report: Report; isCurrent: boolean } | null; compliance: Compliance;
  history: ReviewHistoryRow[]; assignmentHistory: { assetId: string; role: string; shotType: string; position: number; at: string }[]; shotTypes: ShotType[]; limits: { maxImages: number; maxFilesPerRequest: number }; notes: string[];
};
export type ReviewResult = { saved: boolean; reviewId: string | null; created: boolean; report: Report; compliance: Compliance; unitsBilled: 0; message?: string };
export type UploadItem = { name: string; status: "ACCEPTED" | "REJECTED"; code?: string; detail?: string; assetId?: string; alreadyStored?: boolean; widthPx?: number; heightPx?: number };
export type UploadResult = { results: UploadItem[]; assignmentsWritten: number; unitsBilled: 0 };
export type Assignment = { assetId: string; role: Role | "REMOVED"; shotType: string; position?: number };

/** The card the CEO chat shows for an image question (CMO 3.0 M9). Strings are pre-formatted by the backend. */
export type ImageCardFinding = { imageLabel: string; imageNumber: number | null; severity: Severity; problem: string; whyItMatters: string; recommendation: string; isMarketplaceRequirement: false };
export type ImageCard = {
  kind: "IMAGE_QUALITY"; view: "REPORT" | "IMAGE" | "MISSING" | "CLARIFY" | "EMPTY" | "REFUSED" | "ATTACH"; page: string; aiCredits: 0; investigationId?: string; message?: string; question?: string;
  options?: { label: string; sku?: string; marketplace?: string; imageNumber?: number }[]; product?: { sku: string; name: string }; marketplace?: Marketplace; marketplaceName?: string; link?: string;
  scoreState?: Report["scoreState"]; scoreText?: string; dimensions?: { key: string; label: string; state: string; pointsText: string; reason: string | null }[];
  images?: { imageNumber: number; label: string; sizeText: string }[]; findings?: ImageCardFinding[]; moreFindings?: number; missingShots?: Report["missingShots"]; compliance?: { status: Compliance["status"]; marketplace: Marketplace; message: string; notAssessed: string; checks: { rule: string; imageNumber: number | null; result: string; sourceUrl: string; checkedOn: string; scope: string }[] };
  notes?: string[]; reviewSaved?: boolean; focus?: { imageNumber: number; label: string; isLowest?: boolean } | null;
  attachment?: { id: string; filename: string }; products?: { sku: string; name: string }[]; marketplaces?: { key: Marketplace; label: string }[]; shotTypes?: ShotType[];
  preselect?: { sku: string | null; marketplace: Marketplace; role: Role; shotType: string };
};
export const isImageCard = (c: unknown): c is ImageCard => !!c && typeof c === "object" && (c as { kind?: unknown }).kind === "IMAGE_QUALITY" && typeof (c as { view?: unknown }).view === "string";

export type ImagesApi = ReturnType<typeof createImagesApi>;
export function createImagesApi(getToken: GetToken) {
  const post = async <T>(path: string, body: unknown): Promise<T> => apiFetch<T>(`${BASE}${path}`, await getToken(), { method: "POST", body: JSON.stringify(body) });
  return {
    products: async (): Promise<ImageProducts> => apiFetch(`${BASE}/products`, await getToken()),
    page: async (sku: string, marketplace: string): Promise<ImagePage> => apiFetch(`${BASE}?${new URLSearchParams({ sku, marketplace }).toString()}`, await getToken()),
    upload: async (sku: string, marketplace: string, files: { file: File; role: Role; shotType: string }[]): Promise<UploadResult> => {
      const form = new FormData();
      form.append("sku", sku);
      form.append("marketplace", marketplace);
      form.append("labels", JSON.stringify(files.map((f) => ({ role: f.role, shotType: f.shotType }))));
      for (const f of files) form.append("files", f.file);
      return apiFetchForm<UploadResult>(`${BASE}/upload`, await getToken(), form);
    },
    assign: (sku: string, marketplace: string, items: Assignment[]) => post<{ assignmentsWritten: number; unitsBilled: 0 }>("/assign", { sku, marketplace, items }),
    review: (sku: string, marketplace: string) => post<ReviewResult>("/review", { sku, marketplace }),
    addFromChat: (b: { sku: string; marketplace: string; investigationId: string; attachmentId: string; role: Role; shotType: string }) => post<UploadResult>("/from-chat", b),
    /** The seller's own stored picture as a blob URL (the route needs the sign-in token, so an <img src> cannot fetch it directly). */
    file: async (fileUrl: string): Promise<string> => {
      if (demoActive()) return sampleImageUrl(fileUrl); // sample data: a drawn placeholder, nothing is fetched
      const token = await getToken();
      const res = await fetch(`${API_BASE}${fileUrl}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) throw new ApiError(res.status, "image not available");
      return URL.createObjectURL(await res.blob());
    },
  };
}

/** The plain sentence for a failed request. */
export function imageError(e: unknown): string {
  const d = (e as { detail?: unknown })?.detail as { detail?: string; code?: string } | string | undefined;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && typeof d.detail === "string") return d.detail;
  return "That did not work. Nothing was changed.";
}

export const SEVERITY_WORD: Record<Severity, string> = { HIGH: "▲ HIGH", MEDIUM: "◆ MEDIUM", LOW: "● LOW" };
export const SEVERITY_COLOR: Record<Severity, string> = { HIGH: "var(--negative, #E5484D)", MEDIUM: "var(--warning)", LOW: "var(--text-3)" };
export const MARKETPLACE_LABEL: Record<Marketplace, string> = { AMAZON: "Amazon", FLIPKART: "Flipkart", MEESHO: "Meesho" };
