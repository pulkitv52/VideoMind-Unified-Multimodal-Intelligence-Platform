import { expect, test } from "@playwright/test";
import type { Page, Route } from "@playwright/test";
import { fileState, hasLimitations } from "../src/features/sources/fileState";
import type { Asset } from "../src/features/sources/fileState";
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
    if (path === "/api/auth/signup-info") return route.fulfill({ json: { enabled: true } });
    if (path === "/api/auth/me") return route.fulfill({ json: { id: "account", username: "example" } });
    if (path === "/api/auth/logout") return route.fulfill({ status: 204 });
    if (path === "/api/workspaces") return route.fulfill({ json: member ? [{ id: other, name: "Other workspace", role: "member", can_create_collections: false, can_import_folders: false, can_manage_index: false, can_view_analytics: false }, { id: workspace, name: "Example workspace", role: "member", can_create_collections: false, can_import_folders: false, can_manage_index: false, can_view_analytics: false }] : [{ id: workspace, name: "Example workspace", role: "owner", can_create_collections: true, can_import_folders: true, can_manage_index: true, can_view_analytics: true }] });
    if (path.endsWith("/capabilities")) return route.fulfill({ json: { role: member ? "member" : "owner", can_manage_members: !member } });
    if (path.endsWith("/people")) return route.fulfill({ json: { items: [{ principal_id: "account", username: "example", role: "owner", disabled: false }], next_cursor: null } });
    if (path.endsWith("/registration")) return route.fulfill({ json: { configured: true, enabled: true, can_change: !member } });
    if (path.endsWith("/analytics")) return route.fulfill({ json: { can_manage_roles: true, summary: { members: 1, files: 1, ready: 1, preparing: 0, failed: 0, recent_members: 0, recent_uploads: 1 }, people: [{ principal_id: "account", username: "example", role: "owner", disabled: false, joined_at: null, version: 1, files: 1, ready: 1 }], recent_members: [], uploads: [{ id: "asset", title: "example.txt", modality: "document", source_id: source, revision_id: revision, collection: "Example collection", uploader: "example", received_at: "2026-10-26T09:00:00Z", status: "ready", has_warnings: false }], trend: [{ day: "2026-10-26", uploads: 1 }], next_cursor: null, directory_limited: false } });
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

test("owner dashboard shows real activity fields and member route has no analytics", async ({ page }) => {
  const calls = await setup(page);
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
  await expect(page.getByLabel("Workspace totals")).toContainText("Ready to search");
  await expect(page.getByLabel("Upload activity")).toContainText("example.txt");
  await expect(page.getByRole("button", { name: "Close registration", exact: true })).toBeVisible();
  await page.getByLabel("Uploader", { exact: true }).selectOption("account");
  await expect(page.getByLabel("Upload activity")).toContainText("example.txt");
  expect(calls.some(path => path.endsWith("/analytics"))).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("member cannot open analytics by changing the URL", async ({ page }) => {
  const calls = await setup(page, true); await page.goto("/dashboard");
  await expect(page.getByRole("alert")).toContainText("available to workspace owners and admins");
  expect(calls.some(path => path.endsWith("/analytics"))).toBe(false);
  await expect(page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: /^Dashboard/ })).toHaveCount(0);
});

test("signup confirms privacy and opens the member Library after creation", async ({ page }) => {
  await setup(page, true);
  let signedUp = false;
  await page.route("**/api/auth/me", route => signedUp ? route.fulfill({ json: { id: "new-member", username: "new_member" } }) : route.fulfill({ status: 401 }));
  await page.route("**/api/auth/signup", route => {
    const body = route.request().postDataJSON();
    expect(body.accept_workspace_access).toBe(true);
    expect(body.password_confirmation).toBe(body.password);
    expect(body.role).toBeUndefined();
    signedUp = true;
    return route.fulfill({ status: 201, json: { authenticated: true, role: "member" } });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "New here? Create an account", exact: true }).click();
  await page.getByLabel("Username", { exact: true }).fill("new_member");
  await page.getByLabel("Password", { exact: true }).fill("synthetic-password-for-ui");
  await page.getByLabel("Confirm password", { exact: true }).fill("synthetic-password-for-ui");
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Your files, ready to explore." })).toBeVisible();
  await expect(page).toHaveURL(/\/library/);
});

test("collection creation uses server capabilities rather than the displayed role", async ({ page }) => {
  await setup(page);
  await page.route("**/api/workspaces", route => route.fulfill({ json: [{ id: workspace, name: "Example workspace", role: "owner", can_create_collections: false, can_import_folders: false, can_manage_index: false, can_view_analytics: false }] }));
  await page.goto("/library");
  await expect(page.getByRole("heading", { name: "Your files, ready to explore." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add collection", exact: true })).toHaveCount(0);
});

test("admin sees an operational dashboard and a read-only People directory", async ({ page }) => {
  await setup(page);
  await page.route("**/api/workspaces", route => route.fulfill({ json: [{ id: workspace, name: "Example workspace", role: "admin", can_create_collections: true, can_import_folders: true, can_manage_index: true, can_view_analytics: true }] }));
  await page.route(`**/workspaces/${workspace}/capabilities`, route => route.fulfill({ json: { role: "admin", can_manage_members: true } }));
  await page.goto("/settings");
  await expect(page.getByLabel("Your workspace access")).toContainText("Workspace role: Admin");
  await expect(page.getByLabel("People", { exact: true })).toContainText("example");
  await expect(page.getByRole("button", { name: "Start indexing", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /transfer|promote|invite/i })).toHaveCount(0);
});

test("member dashboard lists only granted collections and requests no directory or storage", async ({ page }) => {
  const calls = await setup(page, true);
  await page.route(`**/workspaces/${other}/sources`, route => route.fulfill({ json: [{ id: source, name: "Member collection", connector_kind: "upload", status: "connected", can_ingest: true, can_admin: false }] }));
  await page.goto("/settings");
  await expect(page.getByLabel("Your workspace access")).toContainText("Workspace role: Member");
  await expect(page.getByLabel("Your workspace access")).toContainText("Contributor · can upload");
  await expect(page.getByLabel("People", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /indexing|rebuild|activate|restore/i })).toHaveCount(0);
  expect(calls.some(path => path.endsWith("/people") || path.endsWith("/storage"))).toBe(false);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("directory failure clears previously displayed account and collection details", async ({ page }) => {
  await setup(page);
  await page.route(`**/workspaces/${workspace}/sources`, route => route.fulfill({ json: [{ id: source, name: "Restricted example collection", connector_kind: "upload", status: "connected", can_ingest: true, can_admin: true }] }));
  await page.route(`**/workspaces/${workspace}/people*`, route => route.request().url().includes("after=") ? route.fulfill({ status: 403 }) : route.fulfill({ json: { items: [{ principal_id: "person", username: "restricted-person", role: "member", disabled: false }], next_cursor: source } }));
  await page.goto("/settings");
  await expect(page.getByLabel("People", { exact: true })).toContainText("restricted-person");
  await page.getByRole("button", { name: "More people", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Unable to load people");
  await expect(page.getByLabel("People", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Your workspace access")).not.toContainText("Restricted example collection");
});

test("theme follows the system initially and remembers the user's selection", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await setup(page); await page.goto("/search");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(248, 250, 252)");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(12, 16, 21)");
  await page.setViewportSize({ width: 320, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("theme switching works on sign-in when storage is blocked", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.addInitScript(() => {
    Object.defineProperty(Storage.prototype, "getItem", { value: () => { throw new Error("Storage blocked"); } });
    Object.defineProperty(Storage.prototype, "setItem", { value: () => { throw new Error("Storage blocked"); } });
  });
  await setup(page);
  await page.route("**/api/auth/me", route => route.fulfill({ status: 401 }));
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});
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
  await nav(page, "Library").click(); await expect(page.getByRole("heading", { name: "Your files, ready to explore." })).toBeVisible();
  await nav(page, "Settings").click(); await expect(page.getByRole("heading", { name: "Settings", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Start indexing" })).toBeVisible();
  await page.goBack(); await expect(page.getByRole("heading", { name: "Your files, ready to explore." })).toBeVisible();
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
  await page.goto(`/search?workspace=${workspace}`); await expect(page.getByText("Your files are not searchable yet", { exact: false })).toBeVisible();
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
  await expect(page.getByText("example.txt", { exact: true })).toBeVisible();
  await expect(page.getByText("Upload collection · 1 file", { exact: false })).toBeVisible();
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


test("older dashboard uploads remain visible across the automatic refresh interval", async ({ page }) => {
  await setup(page);
  await page.clock.install();
  let requests = 0;
  await page.route("**/analytics?**", route => {
    requests++;
    const older = new URL(route.request().url()).searchParams.has("after");
    return route.fulfill({ json: { can_manage_roles: true, summary: { members: 1, files: 2, ready: 2, preparing: 0, failed: 0, recent_members: 0, recent_uploads: 2 }, people: [], recent_members: [], uploads: [{ id: older ? "older" : "latest", title: older ? "older.txt" : "latest.txt", modality: "document", source_id: source, revision_id: revision, collection: "Example collection", uploader: "example", received_at: "2026-10-26T09:00:00Z", status: "ready", has_warnings: false }], trend: [], next_cursor: older ? null : "next-page", directory_limited: false } });
  });
  await page.goto("/dashboard");
  await expect(page.getByLabel("Upload activity")).toContainText("latest.txt");
  await page.getByRole("button", { name: "More uploads", exact: true }).click();
  await expect(page.getByLabel("Upload activity")).toContainText("older.txt");
  const pagedRequests = requests;
  await page.clock.runFor(16000);
  await expect(page.getByLabel("Upload activity")).toContainText("older.txt");
  expect(requests).toBe(pagedRequests);
  await page.getByRole("button", { name: "Return to latest activity", exact: true }).click();
  await expect(page.getByLabel("Upload activity")).not.toContainText("older.txt");
  const refreshedRequests = requests;
  await page.clock.runFor(16000);
  await expect.poll(() => requests).toBeGreaterThan(refreshedRequests);
});


const librarySource = { id: source, name: "Example collection", connector_kind: "upload", status: "connected", can_ingest: true, can_admin: true };
const libraryFile = { id: "asset", title: "example.txt", modality: "document", revision_id: revision, size_bytes: 512, status: "stored", error_code: null, job_id: "validate", embedding_status: "indexed", media: null, document: { job_id: "extract", status: "stored", error_code: null, manifest: { page_count: 1 } } };
async function library(page: Page, files = [libraryFile]) {
  await setup(page);
  await page.route(`**/workspaces/${workspace}/sources`, route => route.fulfill({ json: [librarySource] }));
  await page.route(`**/sources/${source}/assets?*`, route => route.fulfill({ json: files, headers: { "X-Total-Count": String(files.length) } }));
  await page.route(`**/sources/${source}/jobs?*`, route => route.fulfill({ json: [] }));
}

test("file readiness requires active membership and retains partial warnings", () => {
  const file: Asset = libraryFile;
  expect(fileState({ ...file, embedding_status: "ready" }).label).toBe("Waiting for publication");
  expect(fileState({ ...file, embedding_status: null }).label).toBe("Preparing search");
  expect(fileState({ ...file, embedding_status: "queued" }).label).toBe("Preparing search");
  expect(fileState({ ...file, embedding_status: "indexed", document: { ...file.document!, status: "failed" } }).label).toBe("Needs attention");
  expect(fileState({ ...file, embedding_status: "cancelled" }).label).toBe("Preparation stopped");
  expect(fileState({ ...file, embedding_status: null, document: { ...file.document!, status: "running" } }).label).toBe("Processing content");
  expect(hasLimitations({ ...file, document: { ...file.document!, manifest: { warnings: ["ocr_partial"] } } })).toBe(true);
});

test("home opens Search for administrators while Dashboard remains available", async ({ page }) => {
  const calls = await setup(page); await page.goto("/");
  await expect(queryBox(page)).toBeVisible();
  expect(calls.some(path => path.endsWith("/analytics"))).toBe(false);
  await nav(page, "Dashboard").click();
  await expect(page.getByRole("heading", { name: "Dashboard", exact: true })).toBeVisible();
});

test("upload batches preserve successes and retry only failed submissions", async ({ page }) => {
  await library(page, []);
  const uploaded: string[] = [];
  let failed = false;
  await page.route(`**/sources/${source}/files?*`, route => {
    const filename = new URL(route.request().url()).searchParams.get("filename_value")!;
    uploaded.push(filename);
    if (filename === "middle.txt" && !failed) { failed = true; return route.fulfill({ status: 503, json: { detail: "Temporarily unavailable" } }); }
    return route.fulfill({ status: 201, json: {} });
  });
  await page.goto("/library");
  await page.getByLabel("Upload files", { exact: true }).setInputFiles(["first.txt", "middle.txt", "last.txt"].map(name => ({ name, mimeType: "text/plain", buffer: Buffer.from("Synthetic upload") })));
  await expect(page.locator(".upload-receipts").getByRole("status")).toContainText("2 of 3 files received");
  expect(uploaded).toEqual(["first.txt", "middle.txt", "last.txt"]);
  await page.getByRole("button", { name: "Retry failed or unsent files" }).click();
  await expect(page.locator(".upload-receipts").getByRole("status")).toContainText("3 of 3 files received");
  expect(uploaded).toEqual(["first.txt", "middle.txt", "last.txt", "middle.txt"]);
});

test("Add files creates a destination only when valid files are chosen", async ({ page }) => {
  await setup(page);
  let created = false; let uploads = 0;
  await page.route(`**/workspaces/${workspace}/sources`, route => {
    if (route.request().method() === "POST") { created = true; expect(route.request().postDataJSON().name).toBe("Project notes"); return route.fulfill({ status: 201, json: librarySource }); }
    return route.fulfill({ json: created ? [librarySource] : [] });
  });
  await page.route(`**/sources/${source}/files?*`, route => { uploads++; return route.fulfill({ status: 201, json: {} }); });
  await page.route(`**/sources/${source}/assets?*`, route => route.fulfill({ json: [], headers: { "X-Total-Count": "0" } }));
  await page.route(`**/sources/${source}/jobs?*`, route => route.fulfill({ json: [] }));
  await page.goto("/library"); await page.getByRole("button", { name: "Add files", exact: true }).click();
  const intake = page.getByRole("region", { name: "Add files", exact: true });
  await intake.getByLabel("New collection name").fill("Project notes");
  await intake.getByLabel("Upload files", { exact: true }).setInputFiles({ name: "bad.exe", mimeType: "application/octet-stream", buffer: Buffer.from("Invalid format") });
  await expect(intake).toContainText("Unsupported file type"); expect(created).toBe(false);
  await intake.getByLabel("Upload files", { exact: true }).setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("Synthetic notes") });
  await expect(intake).toContainText("1 of 1 files received"); expect(uploads).toBe(1);
  await expect(page.getByRole("heading", { name: "Example collection", exact: true })).toBeVisible();
});

test("Library shows primary readiness and keeps retries with processing details", async ({ page }) => {
  await library(page, [{ ...libraryFile, embedding_status: "ready" }]); await page.goto("/library");
  await expect(page.getByText("Waiting for publication", { exact: true })).toBeVisible();
  await expect(page.getByText("Ready to search", { exact: true })).toHaveCount(0);
  await page.getByText("Processing details", { exact: true }).click();
  await expect(page.getByRole("button", { name: "Review search preparation" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Download original", exact: true })).toBeVisible();
});

test("filters can be removed individually without clearing the remaining scope", async ({ page }) => {
  await setup(page); await page.goto("/search");
  await page.getByRole("combobox", { name: "Collection", exact: true }).selectOption(source);
  await page.getByRole("combobox", { name: "File type", exact: true }).selectOption("video");
  await page.getByRole("button", { name: "Remove Type: video filter" }).click();
  await expect(page.getByRole("combobox", { name: "Collection", exact: true })).toHaveValue(source);
  await expect(page.getByRole("combobox", { name: "File type", exact: true })).toHaveValue("");
  await page.getByRole("button", { name: "Clear filters", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Collection", exact: true })).toHaveValue("");
});

test("evidence navigation follows result order and the divider works with a keyboard", async ({ page }) => {
  await setup(page);
  await page.route(`**/workspaces/${workspace}/search`, route => {
    const data = response();
    return route.fulfill({ json: { ...data, results: [data.results[0], { ...data.results[0], segment_id: "second", title: "second.txt", citations: [{ ...data.results[0].citations[0], id: other }] }] } });
  });
  await page.route(`**/citations/${other}`, route => route.fulfill({ json: { locator_kind: "text", revision_id: revision, page: 1, segment_id: "segment", segment_set_id: set } }));
  await page.goto("/search"); await search(page);
  await page.getByRole("button", { name: "test.txt", exact: true }).click();
  await expect(page.getByRole("button", { name: "Previous match" })).toBeDisabled();
  await page.getByRole("button", { name: "Next match" }).click();
  await expect(page).toHaveURL(new RegExp(`citation=${other}`));
  await expect(page.getByRole("button", { name: "Next match" })).toBeDisabled();
  if (page.viewportSize()!.width > 1100) {
    const divider = page.getByRole("separator", { name: "Resize evidence panes" });
    await divider.focus(); await page.keyboard.press("ArrowRight");
    await expect(divider).toHaveAttribute("aria-valuenow", "42");
  }
  await page.getByRole("button", { name: "Back to results" }).click();
  await expect(queryBox(page)).toHaveValue("test");
});

test("missing protected preview retains a usable evidence result", async ({ page }) => {
  await setup(page); let previewCalls = 0;
  await page.route(`**/workspaces/${workspace}/search`, route => {
    const data = response();
    return route.fulfill({ json: { ...data, results: [{ ...data.results[0], preview: { route: "document", kind: "page", object_id: other, segment_set_id: set } }] } });
  });
  await page.route(`**/document/objects/${other}?*`, route => { previewCalls++; return route.fulfill({ status: 404 }); });
  await page.goto("/search"); await search(page);
  await page.locator(".result-preview").scrollIntoViewIfNeeded();
  await expect.poll(() => previewCalls).toBe(1);
  await page.getByRole("button", { name: "Open evidence", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Example document" })).toBeVisible();
});


test("drop uploads remain active when navigating away and collections load on selection", async ({ page }) => {
  await library(page, []);
  const otherSource = { ...librarySource, id: other, name: "Second collection" };
  await page.route(`**/workspaces/${workspace}/sources`, route => route.fulfill({ json: [librarySource, otherSource] }));
  let otherLoads = 0; let pending: Route | undefined;
  await page.route(`**/sources/${other}/assets?*`, route => { otherLoads++; return route.fulfill({ json: [], headers: { "X-Total-Count": "0" } }); });
  await page.route(`**/sources/${other}/jobs?*`, route => route.fulfill({ json: [] }));
  await page.route(`**/sources/${source}/files?*`, route => { pending = route; });
  await page.goto("/library");
  await expect(page.getByRole("heading", { name: "Example collection", exact: true })).toBeVisible();
  expect(otherLoads).toBe(0);
  const files = await page.evaluateHandle(() => { const data = new DataTransfer(); data.items.add(new File(["Synthetic dropped text"], "dropped.txt", { type: "text/plain" })); return data; });
  await page.locator(".upload-drop").first().dispatchEvent("drop", { dataTransfer: files });
  await expect.poll(() => !!pending).toBe(true);
  await nav(page, "Search").click();
  await pending!.fulfill({ status: 201, json: {} });
  await nav(page, "Library").click();
  await expect(page.getByRole("status")).toContainText("1 of 1 files received");
  await page.getByRole("combobox", { name: "Collection", exact: true }).selectOption(other);
  await expect.poll(() => otherLoads).toBe(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("Library and evidence layouts remain readable in both themes", async ({ page }, info) => {
  await library(page); await page.goto("/library");
  await expect(page.getByText("Ready to search", { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: info.outputPath("library-light.png"), fullPage: true });
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await page.screenshot({ path: info.outputPath("library-dark.png"), fullPage: true });
  await nav(page, "Search").click(); await search(page);
  await page.getByRole("button", { name: "Open evidence", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Example document" })).toBeVisible();
  await page.screenshot({ path: info.outputPath("evidence-dark.png"), fullPage: false });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("retry keeps the original upload destination after selection changes", async ({ page }) => {
  await library(page, []);
  await page.route(`**/workspaces/${workspace}/sources`, route => route.fulfill({ json: [librarySource, { ...librarySource, id: other, name: "Second collection" }] }));
  const submissions: string[] = [];
  await page.route("**/sources/*/files?*", route => {
    submissions.push(new URL(route.request().url()).pathname);
    return route.fulfill(submissions.length === 1 ? { status: 503, json: { detail: "Try again" } } : { status: 201, json: {} });
  });
  await page.goto("/library"); await page.getByRole("button", { name: "Add files", exact: true }).click();
  const intake = page.getByRole("region", { name: "Add files", exact: true });
  await intake.getByLabel("Upload files", { exact: true }).setInputFiles({ name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("Synthetic notes") });
  await expect(intake).toContainText("0 of 1 files received");
  await intake.getByRole("combobox", { name: "Destination collection", exact: true }).selectOption(other);
  await intake.getByRole("button", { name: "Retry failed or unsent files" }).click();
  await expect(intake).toContainText("1 of 1 files received");
  expect(submissions).toEqual([`/api/workspaces/${workspace}/sources/${source}/files`, `/api/workspaces/${workspace}/sources/${source}/files`]);
});

test("protected image previews load with at most three simultaneous requests", async ({ page }) => {
  await setup(page); await page.setViewportSize({ width: 1440, height: 4000 });
  await page.route(`**/workspaces/${workspace}/search`, route => {
    const data = response(); const hit = data.results[0];
    return route.fulfill({ json: { ...data, results: Array.from({ length: 10 }, (_, index) => ({ ...hit, segment_id: `segment-${index}`, title: index ? `result-${index}.txt` : "test.txt", preview: { kind: "page", route: "document", object_id: other, segment_set_id: set } })) } });
  });
  const pending: Route[] = []; let calls = 0;
  await page.route(`**/document/objects/${other}?*`, route => { calls++; pending.push(route); });
  await page.goto("/search"); await search(page);
  await expect.poll(() => pending.length).toBe(3);
  await expect(page.locator(".result-preview").nth(4)).toBeInViewport();
  expect(calls).toBe(3);
  const image = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aG1sAAAAASUVORK5CYII=", "base64");
  const first = pending.shift()!;
  await first.fulfill({ contentType: "image/png", body: image });
  await expect.poll(() => calls).toBe(4);
  await expect(page.locator(".result-preview img").first()).toBeVisible();
  await expect.poll(() => page.locator(".result-preview img").first().evaluate((element: HTMLImageElement) => element.naturalWidth)).toBe(1);
});

test("opening a cited passage keeps the results page at its current scroll position", async ({ page }) => {
  await setup(page); await page.goto("/search"); await search(page);
  if (page.viewportSize()!.width <= 1100) return;
  const open = page.getByRole("button", { name: "Open evidence", exact: true });
  await open.scrollIntoViewIfNeeded();
  const previous = await page.evaluate(() => window.scrollY);
  await open.click();
  await expect(page.getByText("Cited passage", { exact: false })).toBeVisible();
  expect(await page.evaluate(() => window.scrollY)).toBe(previous);
});
