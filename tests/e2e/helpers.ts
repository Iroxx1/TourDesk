// Shared accounts and steps of the E2E tests.
import { expect, type Page } from "@playwright/test";

export const ADMIN = { username: "admin", email: "admin@tourdesk.local", password: "Admin-Passwort-123" };
export const USER = { username: "maria", email: "maria@tourdesk.local", password: "Konzerte-2027-Saar" };

export async function login(page: Page, username: string, password: string, expectDesktop = true) {
  await page.goto("/");
  await page.getByLabel("Benutzername oder E-Mail").fill(username);
  await page.getByLabel("Passwort", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Anmelden" }).click();
  if (expectDesktop) await expect(page.locator(".desktop")).toBeVisible();
}

export async function closeWindows(page: Page) {
  for (let i = 0; i < 10; i++) {
    const close = page.locator(".window:not(.is-hidden) .wc-close");
    if ((await close.count()) === 0) return;
    await close.first().click();
  }
}
