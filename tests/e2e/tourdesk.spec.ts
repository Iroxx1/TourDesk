// Full user journey: first-run setup → user management → login → artists → filters →
// explanations → tickets → permissions → admin "view as user" → settings → mobile.
import { expect, test, type Page } from "@playwright/test";
import { ADMIN, USER, closeWindows, login } from "./helpers";

let temporaryPassword = "";

test.describe.configure({ mode: "serial" });

/** The administration window opens by itself after an admin login (once per browser session). */
async function openAdministration(page: Page) {
  const admin = page.locator(".window", { hasText: "TourDesk Administration" });
  try {
    await admin.waitFor({ state: "visible", timeout: 2500 });
  } catch {
    await page.locator(".desktop-icon", { hasText: "Administration" }).click();
    await expect(admin).toBeVisible();
  }
  return admin;
}

async function logout(page: Page) {
  await page.getByRole("button", { name: "Start" }).click();
  await page.getByRole("button", { name: "Abmelden" }).click();
  await expect(page.getByRole("button", { name: "Anmelden" })).toBeVisible();
}

test("Ersteinrichtung legt den Administrator an", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Willkommen bei TourDesk" })).toBeVisible();
  await page.getByLabel("Benutzername").fill(ADMIN.username);
  await page.getByLabel("E-Mail-Adresse").fill(ADMIN.email);
  const pw = page.locator('input[autocomplete="new-password"]');
  await pw.nth(0).fill(ADMIN.password);
  await pw.nth(1).fill(ADMIN.password);
  await page.getByRole("button", { name: "Admin-Konto erstellen" }).click();
  // admins land on the administration overview
  const admin = page.locator(".window", { hasText: "TourDesk Administration" });
  await expect(admin).toBeVisible();
  await expect(admin.getByText("Benutzer (1 aktiv)")).toBeVisible();
});

test("Admin legt einen Benutzer mit temporärem Passwort an", async ({ page }) => {
  await login(page, ADMIN.username, ADMIN.password);
  const admin = await openAdministration(page);
  await admin.locator(".settings-nav-item", { hasText: "Benutzer" }).click();
  await admin.getByRole("button", { name: "Neu" }).click();
  const dialog = page.getByRole("dialog", { name: "Neuer Benutzer" });
  await dialog.getByLabel("Benutzername").fill(USER.username);
  await dialog.getByLabel("E-Mail").fill(USER.email);
  await dialog.getByRole("button", { name: "Anlegen" }).click();
  temporaryPassword = (await page.locator(".temp-password-value").innerText()).trim();
  expect(temporaryPassword.length).toBeGreaterThanOrEqual(10);
  await page.getByRole("button", { name: "Fertig" }).click();
  await expect(admin.locator(".master-item", { hasText: USER.email })).toBeVisible();
  await logout(page);
});

test("Falsches Passwort wird abgelehnt, temporäres Passwort muss geändert werden", async ({ page }) => {
  await login(page, USER.username, "falsches-passwort", false);
  await expect(page.getByText("Benutzername oder Passwort ist falsch.")).toBeVisible();
  await login(page, USER.username, temporaryPassword, false);
  await expect(page.getByRole("heading", { name: "Neues Passwort festlegen" })).toBeVisible();
  await page.getByLabel("Aktuelles (temporäres) Passwort", { exact: true }).fill(temporaryPassword);
  await page.getByLabel("Neues Passwort", { exact: true }).fill(USER.password);
  await page.getByLabel("Neues Passwort wiederholen", { exact: true }).fill(USER.password);
  await page.getByRole("button", { name: "Passwort speichern" }).click();
  await expect(page.getByRole("heading", { name: "Willkommen bei TourDesk" })).toBeVisible();
});

test("Beispielband hinzufügen – der Crawler liefert die Tour", async ({ page }) => {
  await login(page, USER.username, USER.password);
  await page.getByText("„Beispielband“ mit Demo-Terminen hinzufügen").click();
  const tile = page.locator(".tile", { hasText: "Beispielband" });
  await expect(tile).toBeVisible();
  await expect(tile.getByText("AKTUELL AUF TOUR")).toBeVisible({ timeout: 60_000 });
  // the artist appears as an app icon in the taskbar
  await expect(page.locator(".tb-artist").first()).toBeVisible();
});

test("Hierarchische Filter: Saarland komplett, in Luxemburg nur die Rockhal", async ({ page }) => {
  await login(page, USER.username, USER.password);
  await page.locator(".desktop-icon", { hasText: "Filter" }).click();
  const win = page.locator(".window", { hasText: "Meine Orte" });
  await win.getByPlaceholder("Region filtern").fill("Saar");
  await win.locator(".picker-item", { hasText: "Saarland" }).getByRole("button", { name: "Hinzufügen" }).click();
  await expect(win.locator(".rule-group", { hasText: "Deutschland" })).toContainText("Saarland komplett");
  await win.getByRole("radio", { name: "Veranstaltungsort" }).click();
  await win.getByPlaceholder("Veranstaltungsort suchen, z. B. Rockhal, Garage").fill("Rockhal");
  await win.locator(".picker-item", { hasText: "Rockhal" }).first().getByRole("button", { name: "Hinzufügen" }).click();
  await expect(win.locator(".rule-group", { hasText: "Luxemburg" })).toContainText("nur Rockhal");
  await closeWindows(page);

  const tile = page.locator(".tile", { hasText: "Beispielband" });
  await expect(tile.locator(".event-line", { hasText: "Rockhal" })).toBeVisible();
  await expect(tile.locator(".event-line", { hasText: "Garage" })).toBeVisible();
  await expect(tile.locator(".event-line", { hasText: "den Atelier" })).toHaveCount(0);

  // expanding the tile shows the complete tour, events outside the filters are dimmed
  await tile.getByRole("button", { name: "Gesamte Tour anzeigen" }).click();
  const tour = tile.locator(".tile-tour");
  await expect(tour.locator(".event-line.is-outside", { hasText: "den Atelier" })).toBeVisible();
  await expect(tour.locator(".event-line.is-outside", { hasText: "Arena Trier" })).toBeVisible();
  await expect(tour.locator(".event-line:not(.is-outside)", { hasText: "Neue Gebläsehalle" })).toBeVisible();
});

test("Erklärung, warum ein Event nicht angezeigt wird, und echte Ticketlinks", async ({ page }) => {
  await login(page, USER.username, USER.password);
  await page.getByRole("button", { name: "Beispielband öffnen" }).click();
  const artist = page.locator(".window", { hasText: "Meine Termine" });
  await artist.getByRole("tab", { name: /Gesamte Tour/ }).click();
  await artist.locator(".event-row", { hasText: "den Atelier" }).click();
  const event = page.locator(".window.is-active");
  await event.locator(".explain-toggle").click();
  await expect(event.getByText("Warum wird dieses Event nicht angezeigt?")).toBeVisible();
  await expect(event.getByText("Luxemburg ist nicht komplett ausgewählt – nur: Rockhal")).toBeVisible();
  await closeWindows(page);

  await page.getByRole("button", { name: "Beispielband öffnen" }).click();
  await page.locator(".window", { hasText: "Meine Termine" }).locator(".event-row", { hasText: "Garage" }).click();
  const garage = page.locator(".window.is-active");
  const buy = garage.getByRole("link", { name: "Tickets kaufen" });
  await expect(buy).toBeVisible();
  await expect(buy).toHaveAttribute("href", /^https:\/\/example\.org\/tickets\//);
  await expect(buy).toHaveAttribute("target", "_blank");
  await garage.locator(".explain-toggle").click();
  await expect(garage.getByText("Saarland ist bevorzugte Region")).toBeVisible();
});

test("Festival-Schalter blendet Festivalauftritte ein", async ({ page }) => {
  await login(page, USER.username, USER.password);
  await page.getByRole("button", { name: "Beispielband öffnen" }).click();
  const artist = page.locator(".window", { hasText: "Meine Termine" });
  const festivalSwitch = artist.getByRole("switch").first();
  const before = await festivalSwitch.getAttribute("aria-checked");
  await festivalSwitch.click();
  await expect(festivalSwitch).toHaveAttribute("aria-checked", before === "true" ? "false" : "true");
  await expect(page.getByText(/Festivals werden angezeigt|Festivals ausgeblendet/)).toBeVisible();
});

test("Benutzer haben keinen Zugriff auf Admin-Funktionen", async ({ page }) => {
  await login(page, USER.username, USER.password);
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page.locator(".start-app", { hasText: "Administration" })).toHaveCount(0);
  const response = await page.request.get("/api/admin/overview");
  expect(response.status()).toBe(403);
  const users = await page.request.get("/api/admin/users");
  expect(users.status()).toBe(403);
});

test("Einstellungen werden pro Benutzer gespeichert (Dark Mode)", async ({ page }) => {
  await login(page, USER.username, USER.password);
  await page.getByRole("button", { name: "Schnelleinstellungen" }).click();
  await page.locator(".qs-tile", { hasText: "Dunkel" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator(".tile", { hasText: "Beispielband" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("Admin öffnet die Ansicht des Benutzers (klar gekennzeichnet, nur lesen)", async ({ page }) => {
  await login(page, ADMIN.username, ADMIN.password);
  const admin = await openAdministration(page);
  await admin.locator(".settings-nav-item", { hasText: "Benutzer" }).click();
  await admin.locator(".master-item", { hasText: USER.email }).click();
  await admin.getByRole("button", { name: "Ansicht als Benutzer öffnen" }).click();
  const banner = page.locator(".impersonation-banner");
  await expect(banner).toContainText(`Ansicht als Benutzer: ${USER.username}`);
  await expect(page.locator(".tile", { hasText: "Beispielband" })).toBeVisible();
  // writes are rejected while viewing as the user
  const csrf = await page.evaluate(async () => (await (await fetch("/api/auth/me")).json()).csrf_token as string);
  const write = await page.request.put("/api/settings", { data: { theme: "light" }, headers: { "X-CSRF-Token": csrf } });
  expect(write.status()).toBe(403);
  expect((await write.json()).detail).toContain("Benutzeransicht");
  await banner.getByRole("button", { name: "Ansicht beenden" }).click();
  await expect(banner).toHaveCount(0);
});

test("Mobile Darstellung: große Karten, Vollbild-Apps, untere Navigation", async ({ browser }) => {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, locale: "de-DE" });
  const page = await context.newPage();
  await login(page, USER.username, USER.password);
  await expect(page.locator(".mobile-nav")).toBeVisible();
  await expect(page.locator(".taskbar")).toHaveCount(0);
  const tile = page.locator(".tile", { hasText: "Beispielband" });
  await expect(tile).toBeVisible();
  const box = await tile.boundingBox();
  expect(box && box.width).toBeGreaterThan(330);
  await tile.locator(".tile-media").click();
  const win = page.locator(".window.is-mobile:not(.is-hidden)");
  await expect(win).toBeVisible();
  const winBox = await win.boundingBox();
  expect(winBox && winBox.width).toBeGreaterThanOrEqual(389);
  await win.getByRole("button", { name: "Zurück" }).click();
  await expect(page.locator(".window.is-mobile:not(.is-hidden)")).toHaveCount(0);
  await context.close();
});
