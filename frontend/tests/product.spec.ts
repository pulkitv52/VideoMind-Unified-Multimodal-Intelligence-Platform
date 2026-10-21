import { expect, test } from "@playwright/test";
import type { Page, Route } from "@playwright/test";
import { readLocation, viewUrl } from "../src/app/navigation";
const workspace = "00000000-0000-4000-8000-000000000001";
const other = "00000000-0000-4000-8000-000000000002";
const source = "00000000-0000-4000-8000-000000000003";
const citation = "00000000-0000-4000-8000-000000000004";
const revision = "00000000-0000-4000-8000-000000000005";
const set = "00000000-0000-4000-8000-000000000006";
function response(query = "test") {
  return { results: [{ segment_id: "segment", title: `${query}.txt`, source_name: "Example collection", modality: "document", asset: { source_id: source, asset_id: "asset", revision_id: revision }, representation: "text", matched_representations: ["text"], snippet: "A safe synthetic passage.", citations: [{ id: citation, anchor: { locator: { kind: "text_span", start_char: 0, end_char: 25 } } }], warnings: [], branches: { lexical: { rank: 1, score: 1 } }, fusion_score: 1, dense_score: null, context: [] }], no_useful_evidence: false, generation_id: "generation", request_id: "request", retrieval_config_sha256: "config", timings_ms: { total: 200 }, warnings: [] };
}
async function setup(page: Page, member = false) {
  const calls: string[] = [];
  await page.route("**/health/ready", route => route.fulfill({ json: { ready: true } }));
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url()); const path = url.pathname;
    calls.push(path);
    if (path === "/api/auth/me") return route.fulfill({ json: { id: "account", username: "example" } });
    if (path === "/api/auth/logout") return route.fulfill({ status: 204 });
    if (path === "/api/workspaces") return route.fulfill({ json: member ? [{ id: other, name: "Other workspace", role: "member" }, { id: workspace, name: "Example workspace", role: "member" }] : [{ id: workspace, name: "Example workspace", role: "owner" }] });
    if (path.endsWith("/search/facets")) return route.fulfill({ json: { ready: true, items: [{ source_id: source, source_name: "Example collection", modality: "document", assets: 1 }] } });
    if (path.endsWith("/search")) return route.fulfill({ json: response(route.request().postDataJSON().query) });
    if (path.endsWith("/sources")) return route.fulfill({ json: [] });
    if (path.endsWith("/storage")) return route.fulfill({ json: { bytes: 1024, limit_bytes: 1024 ** 3 } });
    if (path.endsWith("/indexes")) return route.fulfill({ json: { can_manage: !member, generations: [] } });
    if (path.endsWith(`/citations/${citation}`)) return route.fulfill({ json: { locator_kind: "text_span", revision_id: revision, page: 1, segment_id: "segment", segment_set_id: set } });
    if (path.endsWith("/document")) return route.fulfill({ json: { title: "Example document", revision_id: revision, segment_set_id: set, manifest: { kind: "text", warnings: [], rendering_object_id: null }, pages: [{ page: 1, image_object_id: null, ocr: false }] } });
    if (path.endsWith("/document/pages/1")) return route.fulfill({ json: { page: 1, image_object_id: null, manifest: { lines: [] }, segments: [{ id: "segment", representation: "text", text_content: "A safe synthetic passage.", citation_id: citation, start_char: 0, end_char: 25, transform: { box: null } }] } });
    return route.fulfill({ status: 500, json: { detail: "Unexpected fixture request" } });
  });
  return calls;
}
const queryBox = (page: Page) => page.getByRole("searchbox", { name: "Describe a passage, scene or sound" });
const nav = (page: Page, name: string) => page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: new RegExp(`^${name}`) });
async function search(page: Page, query = "test") { await queryBox(page).fill(query); await page.getByRole("button", { name: "Search", exact: true }).click(); await expect(page.getByRole("heading", { name: `${query}.txt`, exact: true })).toBeVisible(); }

test("location parsing preserves legacy citations and rejects malformed identifiers", () => {
  expect(readLocation("/", `?workspace=${workspace}&source=${source}&citation=${citation}`).evidence).toEqual({ workspace, source, citation });
  expect(readLocation("/search", "?workspace=bad&source=bad&citation=bad").invalidEvidence).toBe(true);
  expect(viewUrl("search", workspace)).not.toContain("query=");
});

test("navigation preserves search state and mounts Library only on demand", async ({ page }) => {
  const calls = await setup(page); await page.goto("/search");
  await search(page, "cancellation policy");
  expect(calls.some(path => path.endsWith("/sources"))).toBe(false);
  await nav(page, "Library").click(); await expect(page.getByRole("heading", { name: "Files worth finding again." })).toBeVisible();
  await nav(page, "Settings").click(); await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start indexing" })).toBeVisible();
  await page.goBack(); await expect(page.getByRole("heading", { name: "Files worth finding again." })).toBeVisible();
  await nav(page, "Search").click(); await expect(queryBox(page)).toHaveValue("cancellation policy");
  await expect(page.getByRole("heading", { name: "cancellation policy.txt" })).toBeVisible();
  expect(page.url()).not.toContain("cancellation");
});

test("evidence preserves the citation and browser history restores the result", async ({ page }) => {
  await setup(page); await page.goto("/search"); await search(page);
  await page.getByRole("button", { name: "Open evidence", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Example document" })).toBeVisible();
  await expect(page.getByText("Cited passage", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Copy citation", exact: true })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`citation=${citation}`));
  if (page.viewportSize()!.width <= 1100) { expect(await queryBox(page).evaluate(element => !!element.closest("[inert]"))).toBe(true); await expect(page.locator("body")).toHaveCSS("overflow", "hidden"); }
  else await expect(queryBox(page)).toBeVisible();
  await page.goBack(); await expect(page.getByRole("heading", { name: "Example document" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "test.txt" })).toBeVisible();
  expect(await page.locator("body").evaluate(body => body.style.overflow)).toBe("");
  await page.goForward(); await expect(page.getByRole("heading", { name: "Example document" })).toBeVisible();
});

test("old citation link selects the authorised requested workspace and member controls", async ({ page }) => {
  const calls = await setup(page, true);
  await page.goto(`/?workspace=${workspace}&source=${source}&citation=${citation}`);
  await expect(page.getByRole("heading", { name: "Example document" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Workspace", exact: true })).toHaveValue(workspace);
  await page.getByRole("button", { name: "Back to results" }).click();
  await nav(page, "Settings").click();
  await expect(page.getByText("Your workspace administrator manages the search index.", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start indexing" })).toHaveCount(0);
  expect(calls.some(path => path.endsWith("/storage"))).toBe(false);
});

test("foreign citation workspace is denied without fetching its content", async ({ page }) => {
  const calls = await setup(page);
  await page.goto(`/?workspace=${other}&source=${source}&citation=${citation}`);
  await expect(page.getByText("Evidence unavailable. Check the link", { exact: false })).toBeVisible();
  expect(calls.some(path => path.includes("/citations/"))).toBe(false);
});

test("clipboard denial offers a selectable stable link", async ({ page }) => {
  await setup(page); await page.addInitScript(() => { Object.defineProperty(navigator, "clipboard", { value: { writeText: () => Promise.reject(new Error("denied")) } }); });
  await page.goto(`/?workspace=${workspace}&source=${source}&citation=${citation}`);
  await page.getByRole("button", { name: "Copy citation", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Copy this link" })).toHaveValue(new RegExp(`citation=${citation}`));
});

test("previous responses cannot replace a newer query after switching mode", async ({ page }) => {
  await setup(page); let held: Route | undefined;
  await page.route(`**/workspaces/${workspace}/search`, route => {
    const query = route.request().postDataJSON().query;
    if (query === "old") { held = route; return; }
    return route.fulfill({ json: response(query) });
  });
  await page.goto("/search"); await search(page, "initial");
  await queryBox(page).fill("old"); await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Previous results" })).toBeVisible();
  await expect.poll(() => !!held).toBe(true);
  await page.getByRole("button", { name: "Image", exact: true }).click();
  await page.getByRole("button", { name: "Text", exact: true }).click();
  await search(page, "new");
  await held!.fulfill({ json: response("old") });
  await expect(page.getByRole("heading", { name: "new.txt", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "old.txt", exact: true })).toHaveCount(0);
});

test("image query stays transient and preserves endpoint and payload", async ({ page }) => {
  await setup(page); let received = false;
  await page.route(`**/workspaces/${workspace}/search/image`, route => { const data = route.request().postDataJSON(); received = !!data.image_base64 && !data.query; return route.fulfill({ json: response("image") }); });
  await page.goto("/search"); await page.getByRole("button", { name: "Image", exact: true }).click();
  await page.getByLabel("Query image").setInputFiles({ name: "example.png", mimeType: "image/png", buffer: Buffer.from("synthetic fixture") });
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("heading", { name: "image.txt" })).toBeVisible(); expect(received).toBe(true);
  expect(await page.evaluate(() => localStorage.length)).toBe(0);
  await nav(page, "Library").click(); await nav(page, "Search").click();
  await expect(page.getByAltText("Selected query image")).toBeVisible();
});

test("no-index guidance is permission aware and no-results differs from failure", async ({ page }) => {
  await setup(page, true);
  await page.route("**/search/facets", route => route.fulfill({ json: { ready: false, items: [] } }));
  await page.goto(`/search?workspace=${workspace}`); await expect(page.getByText("Your workspace administrator needs", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Set up search" })).toHaveCount(0);
  await page.unroute("**/search/facets"); await page.reload();
  await page.route(`**/workspaces/${workspace}/search`, route => route.fulfill({ json: { ...response(), results: [], no_useful_evidence: true } }));
  await queryBox(page).fill("unrelated"); await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("heading", { name: "No useful matches found" })).toBeVisible();
  await page.unroute(`**/workspaces/${workspace}/search`);
  await page.route(`**/workspaces/${workspace}/search`, route => route.fulfill({ status: 503, json: { detail: "CPU is busy. Try again shortly." } }));
  await page.getByRole("button", { name: "Search", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("CPU is busy");
});

test("reflow keeps the page within 320 CSS pixels", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 }); await setup(page); await page.goto("/search"); await search(page, "a long query with several descriptive words");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("button", { name: "Open evidence", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Example document" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});


test("Library distinguishes loading from an empty collection", async ({ page }) => {
  await setup(page);
  await page.route(`**/workspaces/${workspace}/sources`, route => route.fulfill({ json: [{ id: source, name: "Example collection", connector_kind: "upload", status: "connected", can_ingest: false, can_admin: false }] }));
  let pending: Route | undefined;
  await page.route(`**/sources/${source}/assets?*`, route => { pending = route; });
  await page.route(`**/sources/${source}/jobs?*`, route => route.fulfill({ json: [] }));
  await page.goto("/library");
  await expect(page.getByText("Loading files…", { exact: true })).toBeVisible();
  await expect(page.getByText("Choose files above to add your first originals.", { exact: true })).toHaveCount(0);
  await expect.poll(() => !!pending).toBe(true);
  await pending!.fulfill({ json: [{ id: "asset", title: "example.txt", modality: "document", size_bytes: 512, status: "stored", error_code: null, embedding_status: "indexed", document: null, media: null }], headers: { "X-Total-Count": "1" } });
  await expect(page.getByRole("link", { name: "example.txt", exact: true })).toBeVisible();
  await expect(page.getByText("Upload collection · 1 files", { exact: false })).toBeVisible();
});


test("browser Back closes a Library dialog before returning to Search", async ({ page }) => {
  await setup(page);
  await page.route(`**/workspaces/${workspace}/sources`, route => route.fulfill({ json: [{ id: source, name: "Example collection", connector_kind: "upload", status: "connected", can_ingest: false, can_admin: false }] }));
  await page.route(`**/sources/${source}/assets?*`, route => route.fulfill({ json: [{ id: "asset", title: "example.txt", modality: "document", revision_id: revision, size_bytes: 512, status: "stored", error_code: null, embedding_status: "indexed", media: null, document: { job_id: "job", status: "stored", error_code: null, manifest: { page_count: 1 } } }], headers: { "X-Total-Count": "1" } }));
  await page.route(`**/sources/${source}/jobs?*`, route => route.fulfill({ json: [] }));
  await page.goto("/search"); await nav(page, "Library").click();
  await page.getByRole("button", { name: "Open document", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(queryBox(page)).toBeVisible();
});
