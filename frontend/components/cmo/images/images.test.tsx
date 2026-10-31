import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ImagesDashboard } from "@/components/cmo/images/ImagesDashboard";
import { ImageQualityCard } from "@/components/ceo/hub/ImageQualityCard";
import { ReadinessCard } from "@/components/ceo/hub/ReadinessCard";
import { ApiError } from "@/lib/api";
import { imageError, isImageCard } from "@/lib/cmoImages";
import type { Compliance, Dimension, Finding, ImageCard, ImagePage, ImageProducts, ImagesApi, Report, StoredImage } from "@/lib/cmoImages";

const SHOTS = [{ key: "FRONT", label: "front view" }, { key: "ANGLE", label: "angled view" }, { key: "DETAIL", label: "close-up detail" }, { key: "OTHER", label: "other view" }];
const PRODUCTS: ImageProducts = {
  products: [{ sku: "aqua", name: "AquaNest bottle", sets: [{ marketplace: "AMAZON", images: 2 }] }, { sku: "lamp", name: "BrightBeam lamp", sets: [] }],
  marketplaces: ["AMAZON", "FLIPKART", "MEESHO"], shotTypes: SHOTS, limits: { maxImages: 12, maxFilesPerRequest: 8 },
};
const dim = (key: string, label: string, max: number, over: Partial<Dimension> = {}): Dimension => ({ key, label, max, state: "ASSESSED", earned: max - 2, assessableMax: max, percent: 90, reason: null, ...over });
const finding = (over: Partial<Finding> = {}): Finding => ({ imageNumber: 1, imageId: "i1", role: "PRIMARY", shotType: "FRONT", code: "BLURRY", severity: "HIGH", problem: "The image looks blurry", whyItMatters: "A blurry product picture hides detail.", recommendation: "Re-shoot with a steady camera.", evidence: { sharpnessIndex: 90 }, isMarketplaceRequirement: false, ...over });
const report = (over: Partial<Report> = {}): Report => ({
  method: "m9-image-review-1", scoreState: "COMPLETE", score: 78, maxScore: 100, pointsEarned: 78, pointsAssessable: 100,
  dimensions: [dim("clarity", "Image clarity", 20), dim("lighting", "Lighting and exposure", 15), dim("visibility", "Product visibility", 20), dim("composition", "Composition and cropping", 15), dim("background", "Background quality", 15), dim("set", "Image-set consistency and coverage", 15)],
  images: [{ imageNumber: 1, imageId: "i1", role: "PRIMARY", shotType: "FRONT", widthPx: 1000, heightPx: 1000, dimensions: { clarity: 80, lighting: 100, visibility: null }, notAssessed: { visibility: "The background is too varied." }, overlayCheck: "NOT_DETECTED", overlayCheckConfidence: "LOW" },
    { imageNumber: 2, imageId: "i2", role: "SECONDARY", shotType: "ANGLE", widthPx: 1000, heightPx: 1000, dimensions: { clarity: 90 }, notAssessed: {}, overlayCheck: "POSSIBLE_OVERLAY", overlayCheckConfidence: "LOW" }],
  findings: [finding(), finding({ imageNumber: 2, role: "SECONDARY", shotType: "ANGLE", code: "TOO_DARK", severity: "MEDIUM", problem: "The product looks too dark", whyItMatters: "Buyers cannot judge colour.", recommendation: "Add soft light." }), finding({ imageNumber: null, imageId: null, role: null, shotType: null, code: "MISSING_SIZE", severity: "LOW", problem: "No size or dimensions visual", whyItMatters: "Unclear size causes returns.", recommendation: "Add a size image." })],
  missingShots: [{ code: "MISSING_SIZE", shotType: "SIZE", problem: "No size or dimensions visual", whyItMatters: "x", recommendation: "Add a size image.", isMarketplaceRequirement: false }],
  notes: ["This is image quality, not marketplace compliance and not listing readiness."], ...over,
});
const stored = (n: number, role: "PRIMARY" | "SECONDARY"): StoredImage => ({ assetId: `a${n}`, role, shotType: role === "PRIMARY" ? "FRONT" : "ANGLE", position: n, widthPx: 1000, heightPx: 1000, sha256: "s".repeat(64), fileUrl: `/api/v1/cmo/product-images/a${n}/file`, assignedAt: "2026-11-01T00:00:00Z" });
const NA: Compliance = { status: "NOT_ASSESSED", marketplace: "AMAZON", message: "No verified official image rule is recorded for this marketplace, so nothing is checked against marketplace requirements.", notAssessed: "Background colour, aspect ratio, file size, overlay and text rules, and category-specific image rules are NOT_ASSESSED: no verified official rule for them is recorded.", checks: [] };
const page = (over: Partial<ImagePage> = {}): ImagePage => ({
  product: { sku: "aqua", name: "AquaNest bottle" }, marketplace: "AMAZON", images: [stored(1, "PRIMARY"), stored(2, "SECONDARY")], review: { reviewId: "r1", createdAt: "2026-11-01T10:00:00Z", report: report(), isCurrent: true },
  compliance: NA, history: [{ id: "r1", createdAt: "2026-11-01T10:00:00Z", scoreState: "COMPLETE", score: 78, imageCount: 2, method: "m9-image-review-1" }], assignmentHistory: [{ assetId: "a1", role: "PRIMARY", shotType: "FRONT", position: 1, at: "2026-11-01T09:00:00Z" }],
  shotTypes: SHOTS, limits: { maxImages: 12, maxFilesPerRequest: 8 }, notes: [], ...over,
});
const fake = (over: Partial<Record<keyof ImagesApi, unknown>> = {}): ImagesApi => ({
  products: vi.fn(async () => PRODUCTS), page: vi.fn(async () => page()), file: vi.fn(async () => "blob:thumb"),
  upload: vi.fn(async (_s: string, _m: string, files: unknown[]) => ({ results: files.map((_, i) => ({ name: `f${i}`, status: "ACCEPTED" as const })), assignmentsWritten: files.length, unitsBilled: 0 as const })),
  assign: vi.fn(async () => ({ assignmentsWritten: 1, unitsBilled: 0 as const })), review: vi.fn(async () => ({ saved: true, reviewId: "r2", created: true, report: report(), compliance: NA, unitsBilled: 0 as const })),
  addFromChat: vi.fn(async () => ({ results: [{ name: "x", status: "ACCEPTED" as const }], assignmentsWritten: 1, unitsBilled: 0 as const })), ...over,
}) as unknown as ImagesApi;
const png = (name = "a.png", type = "image/png") => new File([new Uint8Array([137, 80, 78, 71])], name, { type });

beforeEach(() => {
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:preview"), revokeObjectURL: vi.fn() }));
});

describe("the images page", () => {
  it("shows the gallery with main and additional labels, the score, every dimension, findings with why and advice, and the rule status", async () => {
    render(<ImagesDashboard api={fake()} />);
    expect(await screen.findByTestId("score")).toHaveTextContent("78 / 100");
    const imgs = await screen.findAllByTestId("gallery-image");
    expect(imgs.map((i) => i.getAttribute("data-role"))).toEqual(["PRIMARY", "SECONDARY"]);
    expect(within(imgs[0]).getByText(/MAIN IMAGE/)).toBeInTheDocument();
    for (const k of ["clarity", "lighting", "visibility", "composition", "background", "set"]) expect(screen.getByTestId(`dimension-${k}`)).toBeInTheDocument();
    const fs = screen.getAllByTestId("finding");
    expect(fs[0]).toHaveAttribute("data-severity", "HIGH");
    expect(within(fs[0]).getByText(/Main image 1 \(front view\)/)).toBeInTheDocument();
    expect(within(fs[0]).getByText(/Why it matters to buyers/)).toBeInTheDocument();
    expect(within(fs[0]).getByText(/What to improve/)).toBeInTheDocument();
    expect(within(fs[2]).getByText(/Whole image set/)).toBeInTheDocument();
    expect(screen.getByTestId("compliance")).toHaveAttribute("data-status", "NOT_ASSESSED");
    expect(screen.getByTestId("compliance")).toHaveTextContent("NOT ASSESSED");
    expect(screen.getByText(/not marketplace compliance and not listing readiness/i)).toBeInTheDocument();
    expect(screen.getAllByTestId("history-row")).toHaveLength(1);
    expect(screen.getAllByTestId("per-image")).toHaveLength(2);
  });

  it("withholds the score when the review is partial and says which dimension was not assessed and why", async () => {
    const r = report({ scoreState: "PARTIAL", score: null, pointsEarned: 52, pointsAssessable: 70, dimensions: [dim("clarity", "Image clarity", 20), dim("visibility", "Product visibility", 20, { state: "NOT_ASSESSED", earned: null, assessableMax: 0, reason: "The background is too varied to separate the product from it." })] });
    render(<ImagesDashboard api={fake({ page: vi.fn(async () => page({ review: { reviewId: "r1", createdAt: "2026-11-01T10:00:00Z", report: r, isCurrent: true } })) })} />);
    expect(await screen.findByTestId("score")).toHaveTextContent("Score withheld: 52 of 70 assessable points earned");
    expect(screen.getByTestId("dimension-visibility")).toHaveAttribute("data-state", "NOT_ASSESSED");
    expect(screen.getByTestId("dimension-visibility")).toHaveTextContent("NOT ASSESSED");
    expect(screen.getByTestId("score")).not.toHaveTextContent("/ 100");
  });

  it("says a missing image is not a pass, and an unreviewed or stale set is labelled", async () => {
    const { unmount } = render(<ImagesDashboard api={fake({ page: vi.fn(async () => page({ images: [], review: null, history: [], assignmentHistory: [] })) })} />);
    expect(await screen.findByTestId("gallery-empty")).toHaveTextContent("never counted as a pass");
    expect(screen.getByTestId("no-review")).toHaveTextContent("Add pictures first");
    unmount();
    render(<ImagesDashboard api={fake({ page: vi.fn(async () => page({ review: { reviewId: "r1", createdAt: "2026-11-01T10:00:00Z", report: report(), isCurrent: false } })) })} />);
    expect(await screen.findByTestId("stale")).toHaveTextContent("Review them again");
  });

  it("shows a verified rule check with its source and date, and never calls it compliance", async () => {
    const c: Compliance = { ...NA, status: "CHECKED_FAILED", message: "Only the verified rules listed here were checked. This is not a statement that the images meet every marketplace requirement.",
      checks: [{ rule: "image.min_long_side_px", imageNumber: 1, result: "FAIL", measuredLongSidePx: 600, source: { url: "https://sellercentral.amazon.in/help/x", checkedOn: "2026-10-31", scope: "amazon.in ALL_CATEGORIES", value: 1000 } }] };
    render(<ImagesDashboard api={fake({ page: vi.fn(async () => page({ compliance: c })) })} />);
    const box = await screen.findByTestId("compliance");
    expect(box).toHaveTextContent("a verified rule check FAILED");
    expect(box).toHaveTextContent("https://sellercentral.amazon.in/help/x");
    expect(box).toHaveTextContent("checked 2026-10-31");
    expect(box.textContent?.toLowerCase()).not.toMatch(/\bis compliant\b|\bcompliant:/);
  });

  it("lists products and marketplaces, and switching loads that product's pictures", async () => {
    const api = fake();
    render(<ImagesDashboard api={api} />);
    await screen.findByTestId("score");
    await userEvent.selectOptions(screen.getByLabelText("Marketplace"), "FLIPKART");
    await waitFor(() => expect(api.page).toHaveBeenLastCalledWith("aqua", "FLIPKART"));
    await userEvent.selectOptions(screen.getByLabelText("Product"), "lamp");
    await waitFor(() => expect(api.page).toHaveBeenLastCalledWith("lamp", "FLIPKART"));
  });

  it("tells a seller with no products what to do first", async () => {
    render(<ImagesDashboard api={fake({ products: vi.fn(async () => ({ ...PRODUCTS, products: [] })) })} />);
    expect(await screen.findByTestId("no-products")).toHaveTextContent("Tell the CEO about a product");
  });

  it("shows a load failure in plain words", async () => {
    render(<ImagesDashboard api={fake({ products: vi.fn(async () => { throw new ApiError(500, { detail: "Server trouble." }); }) })} />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("previews chosen pictures, labels them, rejects the wrong type, and uploads with the labels in order", async () => {
    const api = fake();
    render(<ImagesDashboard api={api} />);
    const input = await screen.findByLabelText("Choose product pictures");
    await userEvent.upload(input, [png("front.png"), png("detail.png")], { applyAccept: false });
    expect(await screen.findAllByTestId("pending-image")).toHaveLength(2);
    expect(screen.getByAltText("Preview of front.png")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Role of front.png"), "PRIMARY");
    await userEvent.selectOptions(screen.getByLabelText("Kind of shot for front.png"), "FRONT");
    await userEvent.selectOptions(screen.getByLabelText("Kind of shot for detail.png"), "DETAIL");
    await userEvent.click(screen.getByRole("button", { name: /Upload 2 pictures/ }));
    await waitFor(() => expect(api.upload).toHaveBeenCalledTimes(1));
    const [sku, mp, files] = (api.upload as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect([sku, mp]).toEqual(["aqua", "AMAZON"]);
    expect((files as { role: string; shotType: string; file: File }[]).map((f) => [f.file.name, f.role, f.shotType])).toEqual([["front.png", "PRIMARY", "FRONT"], ["detail.png", "SECONDARY", "DETAIL"]]);
    expect(await screen.findAllByTestId("upload-result")).toHaveLength(2);
  });

  it("refuses a non-image file before it is sent and reports a rejected file with its reason", async () => {
    const api = fake({ upload: vi.fn(async () => ({ results: [{ name: "bad.png", status: "REJECTED" as const, code: "CORRUPT", detail: "This image is damaged." }], assignmentsWritten: 0, unitsBilled: 0 as const })) });
    render(<ImagesDashboard api={api} />);
    const input = await screen.findByLabelText("Choose product pictures");
    await userEvent.upload(input, [png("notes.pdf", "application/pdf")], { applyAccept: false });
    expect(await screen.findByRole("alert")).toHaveTextContent("not a PNG, JPEG or WebP");
    expect(screen.queryByTestId("pending-image")).not.toBeInTheDocument();
    await userEvent.upload(input, [png("bad.png")], { applyAccept: false });
    await userEvent.click(await screen.findByRole("button", { name: /Upload 1 picture/ }));
    expect(await screen.findByTestId("upload-result")).toHaveTextContent("not added. This image is damaged.");
  });

  it("will not upload two main images", async () => {
    const api = fake();
    render(<ImagesDashboard api={api} />);
    const input = await screen.findByLabelText("Choose product pictures");
    await userEvent.upload(input, [png("a.png"), png("b.png")], { applyAccept: false });
    await userEvent.selectOptions(await screen.findByLabelText("Role of a.png"), "PRIMARY");
    await userEvent.selectOptions(screen.getByLabelText("Role of b.png"), "PRIMARY");
    expect(screen.getByRole("alert")).toHaveTextContent("Only one picture can be the main image");
    expect(screen.getByRole("button", { name: /Upload 2 pictures/ })).toBeDisabled();
    expect(api.upload).not.toHaveBeenCalled();
  });

  it("makes another picture the main image, removes one, and reviews the set, each by an explicit click", async () => {
    const api = fake();
    render(<ImagesDashboard api={api} />);
    const imgs = await screen.findAllByTestId("gallery-image");
    expect(api.assign).not.toHaveBeenCalled();
    await userEvent.click(within(imgs[1]).getByRole("button", { name: "Make main image" }));
    await waitFor(() => expect(api.assign).toHaveBeenLastCalledWith("aqua", "AMAZON", [{ assetId: "a2", role: "PRIMARY", shotType: "ANGLE" }]));
    await userEvent.click(within((await screen.findAllByTestId("gallery-image"))[1]).getByRole("button", { name: "Remove from product" }));
    await waitFor(() => expect(api.assign).toHaveBeenLastCalledWith("aqua", "AMAZON", [{ assetId: "a2", role: "REMOVED", shotType: "ANGLE" }]));
    expect(api.review).not.toHaveBeenCalled();
    await userEvent.click(await screen.findByRole("button", { name: /Review these images again/ }));
    await waitFor(() => expect(api.review).toHaveBeenCalledWith("aqua", "AMAZON"));
  });

  it("shows the reason when a change is refused", async () => {
    const api = fake({ assign: vi.fn(async () => { throw new ApiError(422, { code: "TOO_MANY_IMAGES", detail: "A product can have at most 12 images." }); }) });
    render(<ImagesDashboard api={api} />);
    await userEvent.click(within((await screen.findAllByTestId("gallery-image"))[1]).getByRole("button", { name: "Make main image" }));
    expect(await screen.findByText("A product can have at most 12 images.")).toBeInTheDocument();
  });
});

describe("near-duplicate pictures", () => {
  it("lists which images look alike and why, and marks an uncertain pair as not assessed rather than a repeat", async () => {
    const r = report({ duplicateCheck: { state: "CHECKED", reason: null, pairs: [
      { images: [1, 2], verdict: "REPEAT", hashDistanceOf64: 0, colourDifference: 0, sameKindOfShot: true, reason: "The two pictures have almost the same shapes and colours (difference hash distance 0 of 64, average colour difference 0 of 255)." },
      { images: [1, 3], verdict: "NOT_ASSESSED", hashDistanceOf64: 2, colourDifference: 28, sameKindOfShot: false, reason: "The two pictures are alike but not alike enough to call a repeat; they may be two views of the same product. Not assessed." }] } });
    render(<ImagesDashboard api={fake({ page: vi.fn(async () => page({ review: { reviewId: "r1", createdAt: "2026-11-01T10:00:00Z", report: r, isCurrent: true } })) })} />);
    const pairs = await screen.findAllByTestId("similar-pair");
    expect(pairs.map((p) => p.getAttribute("data-verdict"))).toEqual(["REPEAT", "NOT_ASSESSED"]);
    expect(pairs[0]).toHaveTextContent("Images 1 and 2: look almost the same");
    expect(pairs[1]).toHaveTextContent("Images 1 and 3: NOT ASSESSED");
  });
});

describe("helpers", () => {
  it("turns a refusal into its plain sentence", () => {
    expect(imageError(new ApiError(404, { code: "UNKNOWN_PRODUCT", detail: "That product is not one of yours yet." }))).toBe("That product is not one of yours yet.");
    expect(imageError(new Error("x"))).toContain("Nothing was changed");
  });
  it("recognises only the image card", () => {
    expect(isImageCard({ kind: "IMAGE_QUALITY", view: "REPORT" })).toBe(true);
    expect(isImageCard({ kind: "LISTING_PERFORMANCE", view: "REPORT" })).toBe(false);
    expect(isImageCard(null)).toBe(false);
  });
});

const card = (over: Partial<ImageCard> = {}): ImageCard => ({
  kind: "IMAGE_QUALITY", view: "REPORT", page: "/dashboard/cmo/images", aiCredits: 0, investigationId: "inv-1", product: { sku: "aqua", name: "AquaNest bottle" }, marketplace: "AMAZON", marketplaceName: "Amazon",
  link: "/dashboard/cmo/images?sku=aqua&marketplace=AMAZON", scoreState: "COMPLETE", scoreText: "78 / 100",
  dimensions: [{ key: "clarity", label: "Image clarity", state: "ASSESSED", pointsText: "18 of 20", reason: null }, { key: "visibility", label: "Product visibility", state: "NOT_ASSESSED", pointsText: "Not assessed", reason: "The background is too varied." }],
  images: [{ imageNumber: 1, label: "Main image 1 (front view)", sizeText: "1000 × 1000 px" }],
  findings: [{ imageLabel: "Main image 1 (front view)", imageNumber: 1, severity: "HIGH", problem: "The image looks blurry", whyItMatters: "Hides detail.", recommendation: "Re-shoot.", isMarketplaceRequirement: false },
    { imageLabel: "Additional image 2 (angled view)", imageNumber: 2, severity: "LOW", problem: "Small", whyItMatters: "Zoom.", recommendation: "Larger.", isMarketplaceRequirement: false }],
  moreFindings: 0, missingShots: [], compliance: { status: "NOT_ASSESSED", marketplace: "AMAZON", message: "No verified official image rule is recorded for this marketplace, so nothing is checked against marketplace requirements.", notAssessed: "Other rules are NOT_ASSESSED.", checks: [] },
  notes: [], reviewSaved: true, focus: null, ...over,
});

describe("the CEO chat image card", () => {
  it("shows the score, dimensions, findings by severity with why and advice, and NOT ASSESSED marketplace rules", () => {
    render(<ImageQualityCard card={card()} onSend={vi.fn()} />);
    expect(screen.getByTestId("image-score")).toHaveTextContent("78 / 100");
    expect(screen.getByTestId("dim-visibility")).toHaveTextContent("NOT ASSESSED");
    expect(screen.getAllByTestId("image-finding")).toHaveLength(2);
    expect(screen.getAllByTestId("image-finding")[0]).toHaveAttribute("data-severity", "HIGH");
    expect(within(screen.getAllByTestId("image-finding")[0]).getByText(/Why it matters:/)).toBeInTheDocument();
    expect(screen.getAllByTestId("image-finding")[0]).toHaveTextContent("Hides detail.");
    expect(screen.getByTestId("image-compliance")).toHaveTextContent("Amazon image requirements: NOT ASSESSED");
    expect(screen.getByRole("link", { name: /Open the images page/ })).toHaveAttribute("href", "/dashboard/cmo/images?sku=aqua&marketplace=AMAZON");
  });

  it("focuses on one image when asked", () => {
    render(<ImageQualityCard card={card({ view: "IMAGE", focus: { imageNumber: 2, label: "Additional image 2 (angled view)" } })} onSend={vi.fn()} />);
    expect(screen.getAllByTestId("image-finding")).toHaveLength(1);
    expect(screen.getByText(/Showing:/)).toHaveTextContent("Additional image 2");
  });

  it("says plainly when no issues were found, without implying compliance", () => {
    render(<ImageQualityCard card={card({ findings: [], view: "IMAGE", focus: { imageNumber: 1, label: "Main image 1" } })} onSend={vi.fn()} />);
    expect(screen.getByTestId("image-no-findings")).toHaveTextContent("not a statement that the image meets any marketplace requirement");
  });

  it("offers suggestions for missing photos as suggestions", () => {
    render(<ImageQualityCard card={card({ view: "MISSING", missingShots: [{ code: "MISSING_SIZE", shotType: "SIZE", problem: "No size or dimensions visual", whyItMatters: "x", recommendation: "Add a size image.", isMarketplaceRequirement: false }] })} onSend={vi.fn()} />);
    expect(screen.getByTestId("missing-shot")).toHaveTextContent("a suggestion, not a marketplace requirement");
  });

  it("asks one question with buttons that send the answer as a message", async () => {
    const onSend = vi.fn();
    render(<ImageQualityCard card={card({ view: "CLARIFY", question: "Which product do you mean?", options: [{ label: "AquaNest bottle", sku: "aqua" }, { label: "BrightBeam lamp", sku: "lamp" }] })} onSend={onSend} />);
    await userEvent.click(screen.getByRole("button", { name: "BrightBeam lamp" }));
    expect(onSend).toHaveBeenCalledWith("BrightBeam lamp");
  });

  it("shows an empty or refused answer with the way forward", () => {
    render(<ImageQualityCard card={card({ view: "EMPTY", message: "You have no images uploaded yet." })} onSend={vi.fn()} />);
    expect(screen.getByTestId("image-empty")).toHaveTextContent("no images uploaded");
  });

  describe("a photo attached in the chat", () => {
    const attach = (): ImageCard => ({ kind: "IMAGE_QUALITY", view: "ATTACH", page: "/dashboard/cmo/images", aiCredits: 0, investigationId: "inv-1", attachment: { id: "att-1", filename: "bottle.png" },
      products: [{ sku: "aqua", name: "AquaNest bottle" }], marketplaces: [{ key: "AMAZON", label: "Amazon" }, { key: "FLIPKART", label: "Flipkart" }], shotTypes: SHOTS, preselect: { sku: "aqua", marketplace: "AMAZON", role: "PRIMARY", shotType: "FRONT" } });

    it("is not added until the button is pressed, and the button sends the chosen labels", async () => {
      const api = fake();
      render(<ImageQualityCard card={attach()} api={api} onSend={vi.fn()} />);
      expect(screen.getByTestId("image-attach")).toHaveTextContent("not added yet");
      expect(screen.getByTestId("image-attach")).toHaveTextContent("Typing “yes” does not add it");
      expect(api.addFromChat).not.toHaveBeenCalled();
      await userEvent.selectOptions(screen.getByLabelText("Marketplace"), "FLIPKART");
      await userEvent.click(screen.getByRole("button", { name: "Add to my product images" }));
      await waitFor(() => expect(api.addFromChat).toHaveBeenCalledWith({ sku: "aqua", marketplace: "FLIPKART", investigationId: "inv-1", attachmentId: "att-1", role: "PRIMARY", shotType: "FRONT" }));
      expect(await screen.findByRole("status")).toHaveTextContent("Added to your product images. Nothing was published.");
      expect(screen.getByRole("button", { name: "Add to my product images" })).toBeDisabled();
    });

    it("cannot be pressed without choosing a product", () => {
      const c = attach();
      c.preselect = { sku: null, marketplace: "AMAZON", role: "SECONDARY", shotType: "OTHER" };
      render(<ImageQualityCard card={c} api={fake()} onSend={vi.fn()} />);
      expect(screen.getByRole("button", { name: "Add to my product images" })).toBeDisabled();
    });

    it("shows the reason when the photo is refused", async () => {
      const api = fake({ addFromChat: vi.fn(async () => { throw new ApiError(404, { code: "NOT_FOUND", detail: "That photo was not found in this conversation." }); }) });
      render(<ImageQualityCard card={attach()} api={api} onSend={vi.fn()} />);
      await userEvent.click(screen.getByRole("button", { name: "Add to my product images" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("That photo was not found");
    });
  });
});

describe("readiness shows image quality beside the checklist", () => {
  const market = (iq: unknown) => ({
    marketplace: "AMAZON", verdict: "NOT_READY", verdictText: "Not ready.", score: { status: "ASSESSED", score: 40, earnedPoints: 40, assessablePoints: 100, note: "Based on all 100 points." }, categories: [], nextActions: [],
    counts: { done: 1, missing: 1, blocked: 0, notAssessed: 1 }, imageQuality: iq,
  });
  const rc = (iq: unknown) => ({ version: 1, kind: "READINESS", view: "readiness", notice: "n", investigationId: "inv", product: { name: "AquaNest", sku: "aqua" }, defaultMarketplace: "AMAZON",
    questions: { counts: { CONFIRMED: 0, NOT_CONFIRMED: 0, SELLER_UNKNOWN: 0 }, questions: [], limits: [] }, readiness: { marketplaces: [market(iq)], limits: [] } });

  it("labels missing images as not assessed and a reviewed set with its score, separate from the readiness score", () => {
    const { unmount } = render(<ReadinessCard card={rc({ state: "NOT_ASSESSED", message: "No product images are uploaded for Amazon, so image quality is not assessed. This is not a pass.", note: "Image quality is advice shown beside readiness.", separateFromReadiness: true }) as never} disabled={false} onSend={vi.fn()} />);
    expect(screen.getByTestId("readiness-image-quality")).toHaveTextContent("NOT ASSESSED");
    expect(screen.getByTestId("readiness-image-quality")).toHaveTextContent("not a pass");
    unmount();
    render(<ReadinessCard card={rc({ state: "REVIEWED", message: "Image quality 78/100; 1 high-priority issue(s).", note: "Image quality is advice shown beside readiness; it does not change the readiness score or verdict.", score: 78, highFindings: 1, images: 3, separateFromReadiness: true }) as never} disabled={false} onSend={vi.fn()} />);
    expect(screen.getByTestId("readiness-image-quality")).toHaveTextContent("Image quality 78/100");
    expect(screen.getByTestId("readiness-score")).toHaveTextContent("40/100");
  });
});
