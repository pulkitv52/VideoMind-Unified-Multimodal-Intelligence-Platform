import { expect, test } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

type Account = { username: string; password: string; role: string };
type Collection = { id: string; name: string; member_id: string; permission: string; marker: string };
const root = resolve(import.meta.dirname, "../..");
const fixture = JSON.parse(readFileSync(resolve(root, ".local/role-test-accounts.json"), "utf8")) as { workspace_id: string; accounts: Account[]; collections: Collection[] };
const owner = { ...JSON.parse(readFileSync(resolve(root, ".local/owner.json"), "utf8")), role: "owner" } as Account;
const accounts = [owner, ...fixture.accounts];
mkdirSync(resolve(root, ".local/role-dashboard-screenshots"), { recursive: true });

for (const [index, account] of accounts.entries()) {
  test(`${index === 0 ? "owner" : index === 1 ? "admin" : index === 2 ? "member viewer" : "member contributor"} actual login, dashboard, collection access and evidence`, async ({ page }, info) => {
    await page.goto("/settings");
    await page.getByLabel("Username", { exact: true }).fill(account.username);
    await page.getByLabel("Password", { exact: true }).fill(account.password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    try {
    const panel = page.getByLabel("Your workspace access", { exact: true });
    await expect(panel).toContainText(`Workspace role: ${account.role[0].toUpperCase()}${account.role.slice(1)}`);
    const admin = account.role !== "member";
    await expect(page.getByLabel("People", { exact: true })).toHaveCount(admin ? 1 : 0);
    if (admin) {
      for (const person of accounts) await expect(page.getByLabel("People", { exact: true })).toContainText(person.username);
      await expect(page.getByRole("button", { name: "Rebuild search index", exact: true })).toBeVisible();
    } else {
      const own = fixture.collections[index - 2];
      const hidden = fixture.collections[index === 2 ? 1 : 0];
      await expect(panel).toContainText(own.name);
      await expect(panel).not.toContainText(hidden.name);
      await expect(panel).toContainText(index === 2 ? "Viewer · read only" : "Contributor · can upload");
      await expect(page.getByRole("button", { name: /index|restore/i })).toHaveCount(0);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: resolve(root, `.local/role-dashboard-screenshots/${index}-${info.project.name}.png`), fullPage: true });
    const dashboard = page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: /^Dashboard/ });
    await expect(dashboard).toHaveCount(admin ? 1 : 0);
    if (admin) {
      await dashboard.click();
      await expect(page.getByLabel("Workspace totals")).toBeVisible();
      await expect(page.getByLabel("Members and their files")).toContainText(fixture.accounts[2].username);
      await expect(page.getByRole("button", { name: "Close registration", exact: true })).toHaveCount(account.role === "owner" ? 1 : 0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await page.screenshot({ path: resolve(root, `.local/role-dashboard-screenshots/dashboard-${index}-${info.project.name}.png`), fullPage: true });
    } else expect((await page.request.get(`/api/workspaces/${fixture.workspace_id}/analytics`)).status()).toBe(403);
    await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: /^Library/ }).click();
    await expect(page.getByRole("button", { name: "Add collection", exact: true })).toHaveCount(1);
    if (!admin) {
      await expect(page.getByRole("heading", { name: fixture.collections[index - 2].name, exact: true })).toBeVisible();
      await expect(page.getByText("Upload files", { exact: true })).toHaveCount(index === 3 ? 1 : 0);
      await expect(page.getByRole("button", { name: "Disconnect", exact: true })).toHaveCount(0);
    }
    await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: /^Search/ }).click();
    await page.getByRole("searchbox").fill(fixture.collections[index === 3 ? 1 : 0].marker);
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await expect(page.getByRole("heading", { name: "role-example.txt", exact: true }).first()).toBeVisible({ timeout: 45000 });
    await page.getByRole("button", { name: "Open evidence", exact: true }).first().click();
    await expect(page.getByRole("heading", { name: "role-example.txt", exact: true }).last()).toBeVisible();
    await expect(page.getByRole("button", { name: "Copy citation", exact: true })).toBeVisible();
    // Sign out through the API after closing evidence; each test has an isolated context.
    } finally { await page.request.post("/api/auth/logout"); }
  });
}
