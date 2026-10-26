import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "../..");
const owner = JSON.parse(readFileSync(resolve(root, ".local/owner.json"), "utf8"));
const fixture = JSON.parse(readFileSync(resolve(root, ".local/role-test-accounts.json"), "utf8"));

test("new member signs up, uploads, searches and appears in the admin dashboard", async ({ page, playwright }, info) => {
  test.setTimeout(300000);
  const admin = await playwright.request.newContext({ baseURL: "http://localhost:8080" });
  const peer = await playwright.request.newContext({ baseURL: "http://localhost:8080" });
  const base = `/api/workspaces/${fixture.workspace_id}`;
  const username = `live_signup_${randomBytes(8).toString("hex")}`;
  const password = randomBytes(24).toString("base64url");
  const marker = `selfserviceproof${randomBytes(7).toString("hex")}`;
  let principal = ""; let source = "";
  try {
    expect((await admin.post("/api/auth/login", { data: { username: owner.username, password: owner.password } })).ok()).toBe(true);
    expect((await peer.post("/api/auth/login", { data: { username: fixture.accounts[1].username, password: fixture.accounts[1].password } })).ok()).toBe(true);
    await page.goto("/");
    await page.getByRole("button", { name: "New here? Create an account", exact: true }).click();
    await page.getByLabel("Username", { exact: true }).fill(username);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByLabel("Confirm password", { exact: true }).fill(password);
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Create account", exact: true }).click();
    await expect(page).toHaveURL(/\/library/);
    principal = (await (await page.request.get("/api/auth/me")).json()).id;
    const collections = await (await page.request.get(base + "/sources")).json();
    expect(collections).toHaveLength(1); source = collections[0].id;
    expect(collections[0].can_ingest).toBe(true);
    expect((await page.request.get(base + "/analytics")).status()).toBe(403);
    expect((await peer.get(base + `/sources/${source}`)).status()).toBe(404);
    await page.locator('input[type="file"]').setInputFiles({ name: "selfservice-example.txt", mimeType: "text/plain", buffer: Buffer.from(`${marker}\nA synthetic self-service account uploads a document and searches its evidence.`) });
    await expect.poll(async () => {
      const rows = await (await page.request.get(base + `/sources/${source}/assets`)).json();
      return rows[0]?.embedding_status;
    }, { timeout: 210000, intervals: [2000, 5000] }).toBe("indexed");
    await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: /^Search/ }).click();
    await page.getByRole("searchbox").fill(marker);
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page.getByRole("heading", { name: "selfservice-example.txt", exact: true }).first()).toBeVisible({ timeout: 45000 });
    await page.getByRole("button", { name: "Open evidence", exact: true }).first().click();
    await expect(page.getByRole("button", { name: "Copy citation", exact: true })).toBeVisible();
    const activity = await (await admin.get(base + `/analytics?member=${principal}`)).json();
    expect(activity.uploads).toHaveLength(1);
    expect(activity.uploads[0].uploader).toBe(username);
    expect(activity.uploads[0].status).toBe("ready");
    expect(activity.people.find((person: {principal_id: string}) => person.principal_id === principal).joined_at).toBeTruthy();
    await page.screenshot({ path: resolve(root, `.local/role-dashboard-screenshots/signup-${info.project.name}.png`), fullPage: true });
  } finally {
    if (source) expect((await admin.delete(base + `/sources/${source}`)).status()).toBe(204);
    if (principal) {
      const people = await (await admin.get(base + "/people")).json();
      const member = people.items.find((person: {principal_id: string}) => person.principal_id === principal);
      expect((await admin.post(base + `/people/${principal}`, { data: {version: member.version, role: null} })).ok()).toBe(true);
      expect((await page.request.get(base + "/capabilities")).status()).toBe(404);
    }
    await page.request.post("/api/auth/logout");
    await admin.post("/api/auth/logout"); await peer.post("/api/auth/logout");
    await admin.dispose(); await peer.dispose();
  }
});
