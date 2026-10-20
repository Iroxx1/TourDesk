// Künstlerkatalog: Knopf neben der Suche, Buch mit Register, Umblättern, Genre-/Herkunftsfilter,
// Karteikarte mit „Hinzufügen“/„Abbrechen“ – auf Desktop und Handy, ohne horizontalen Überlauf.
// Läuft nach der User-Journey (deren Benutzer) und füllt den Katalog über fixtures/catalog.py.
// TOURDESK_E2E_SCREENSHOTS=<Verzeichnis> speichert zusätzlich Screenshots.
import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { USER, login } from "./helpers";

const SCREENSHOTS = process.env.TOURDESK_E2E_SCREENSHOTS;

test.beforeAll(() => {
  const root = path.resolve(__dirname, "../..");
  const python = path.join(process.env.TOURDESK_VENV ?? path.join(root, ".venv"), "bin", "python");
  execFileSync(python, [path.join(__dirname, "fixtures", "catalog.py")], { stdio: "inherit" });
});

async function screenshot(page: Page, name: string) {
  if (SCREENSHOTS) await page.screenshot({ path: path.join(SCREENSHOTS, `katalog-${name}.png`) });
}

async function openCatalog(page: Page, mobile: boolean) {
  await login(page, USER.username, USER.password);
  if (mobile) {
    await page.locator(".mobile-nav-btn", { hasText: "Menü" }).click();
    // im Menü (die Startseite hat ebenfalls einen „Künstler“-Knopf, der darunter liegt)
    await page.locator(".flyout-layer").getByRole("button", { name: "Künstler", exact: true }).click();
  } else {
    await page.locator(".desktop-icon", { hasText: "Künstler" }).click();
  }
  const launch = page.getByRole("button", { name: /Katalog/ });
  await expect(launch).toBeVisible();
  await launch.click();
  const book = page.getByRole("dialog", { name: "Künstlerkatalog" });
  await expect(book).toBeVisible();
  await expect(book.locator(".cat-title-main")).toHaveText(/Künstler/);
  return book;
}

/** Nichts im Katalog scrollt horizontal, und die Seite selbst ist nicht breiter als das Fenster. */
async function expectNoHorizontalOverflow(page: Page, label: string) {
  const result = await page.evaluate(() => {
    const bad = [...document.querySelectorAll(".cat-overlay, .cat-overlay *")]
      .filter((e) => e.scrollWidth > e.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(e).overflowX))
      .map((e) => (e.getAttribute("class") ?? e.tagName).slice(0, 40));
    return { bad, page: document.documentElement.scrollWidth - window.innerWidth };
  });
  expect(result.bad, `${label}: horizontaler Scrollbalken`).toEqual([]);
  expect(result.page, `${label}: Seite breiter als das Fenster`).toBeLessThanOrEqual(0);
}

test.describe("Desktop", () => {
  test.use({ viewport: { width: 1440, height: 900 }, contextOptions: { reducedMotion: "reduce" } });

  test("Suche halbiert, Katalog-Knopf daneben", async ({ page }) => {
    await login(page, USER.username, USER.password);
    await page.locator(".desktop-icon", { hasText: "Künstler" }).click();
    const search = page.getByPlaceholder("Name des Künstlers oder der Band");
    const launch = page.getByRole("button", { name: /Katalog/ });
    const [s, l] = [await search.boundingBox(), await launch.boundingBox()];
    expect(s && l).toBeTruthy();
    expect(l!.x, "Katalog rechts neben der Suche").toBeGreaterThan(s!.x + s!.width);
    expect(Math.abs(l!.y - s!.y), "auf einer Höhe").toBeLessThan(30);
  });

  test("Register, Blättern, Filter und Karteikarte", async ({ page }) => {
    const book = await openCatalog(page, false);
    await expect(book.locator(".cat-title-sel")).toContainText("Künstler auf");
    await screenshot(page, "titel");

    // Register: K schlägt die Seite mit Kraftklub auf, das Register zeigt K
    await book.getByRole("button", { name: "Buchstabe K" }).click();
    await expect(book.getByRole("button", { name: /^Kraftklub, Band/ })).toBeVisible();
    await expect(book.getByRole("button", { name: "Buchstabe K" })).toHaveClass(/is-active/);
    const before = await book.locator(".cat-indicator").first().textContent();

    // Blättern mit Pfeiltaste und mit der Ecke
    await page.keyboard.press("ArrowRight");
    await expect(book.locator(".cat-indicator").first()).not.toHaveText(before ?? "");
    await book.getByRole("button", { name: "Zurückblättern" }).click();
    await expect(book.locator(".cat-indicator").first()).toHaveText(before ?? "");

    // Genre: nur Schlager – Helene Fischer und Roland Kaiser
    await book.getByLabel("Genre").selectOption("schlager");
    await book.getByRole("button", { name: "Buchstabe F" }).click();
    await expect(book.getByRole("button", { name: /^Helene Fischer/ })).toBeVisible();
    await expect(book.locator("button.cat-entry")).toHaveCount(2);
    await expect(book.getByRole("button", { name: /^Kraftklub/ })).toHaveCount(0);

    // Herkunft: Rock deutschsprachig (DE/AT/CH) – Wanda und Züri West ja, The Kinks nicht
    await book.getByLabel("Genre").selectOption("rock");
    await book.getByRole("radio", { name: "Deutschsprachig" }).click();
    await book.getByRole("button", { name: "Buchstabe W" }).click();
    await expect(book.getByRole("button", { name: /^Wanda/ })).toBeVisible();
    await book.getByRole("button", { name: "Buchstabe K" }).click();
    await expect(book.getByRole("button", { name: /^Kraftklub/ })).toBeVisible();
    await expect(book.getByRole("button", { name: /^The Kinks/ })).toHaveCount(0);
    await screenshot(page, "rock-dach");

    // Karteikarte: Details, Abbrechen schließt nur die Karte
    await book.getByRole("button", { name: /^Kraftklub/ }).click();
    const card = page.getByRole("dialog", { name: "Kraftklub – Details" });
    await expect(card).toBeVisible();
    await expect(card).toContainText("Kraftklub ist eine deutsche Band aus Chemnitz.");
    await expect(card).toContainText("Band · Deutschland · seit 2008");
    await expect(card.getByRole("link", { name: /Offizielle Website/ })).toHaveAttribute("href", "https://kraftklub.e2e.test/");
    await screenshot(page, "karteikarte");
    await card.getByRole("button", { name: "Abbrechen" }).click();
    await expect(card).toHaveCount(0);
    await expect(book).toBeVisible();

    // Hinzufügen: Karte schließt, Katalog bleibt offen, Eintrag bekommt den Stempel
    await book.getByRole("button", { name: /^Kraftklub/ }).click();
    await page.getByRole("dialog", { name: "Kraftklub – Details" }).getByRole("button", { name: "Hinzufügen" }).click();
    await expect(page.getByText("Kraftklub wird jetzt überwacht")).toBeVisible();
    await expect(page.getByRole("dialog", { name: "Kraftklub – Details" })).toHaveCount(0);
    await expect(book).toBeVisible();
    const entry = book.getByRole("button", { name: /^Kraftklub.*wird überwacht/ });
    await expect(entry).toBeVisible();
    await expect(entry.locator(".cat-stamp")).toHaveText(/überwacht/);
    await entry.click();
    await expect(page.getByRole("dialog", { name: "Kraftklub – Details" }).getByRole("button", { name: "Bereits überwacht" })).toBeDisabled();
    await page.keyboard.press("Escape");

    // Esc schließt den Katalog; Kraftklub steht in „Meine Künstler“
    await page.keyboard.press("Escape");
    await expect(book).toHaveCount(0);
    await expect(page.locator(".artist-row", { hasText: "Kraftklub" })).toBeVisible();
  });
});

test.describe("Animation", () => {
  test.use({ viewport: { width: 1440, height: 900 }, contextOptions: { reducedMotion: "no-preference" } });

  test("Sprung während des Aufschlagens, Seite blättert um", async ({ page }) => {
    const book = await openCatalog(page, false);
    // Sprung, während der Deckel noch aufschlägt: wird nicht verworfen
    await book.getByRole("button", { name: "Buchstabe K" }).click();
    await expect(book.getByRole("button", { name: /^Kraftklub/ })).toBeVisible();
    await expect(book.locator(".cat-cover")).toHaveCount(0);
    const before = await book.locator(".cat-indicator").first().textContent();
    await book.getByRole("button", { name: "Nächste Seite" }).click();
    await expect(book.locator(".cat-leaf.turn-next")).toBeVisible();
    await expect(book.locator(".cat-leaf")).toHaveCount(0, { timeout: 3000 });
    await expect(book.locator(".cat-indicator").first()).not.toHaveText(before ?? "");
  });
});

const VIEWPORTS = [
  { name: "1280x800", width: 1280, height: 800, mobile: false },
  { name: "1920x1080", width: 1920, height: 1080, mobile: false },
  { name: "390x844", width: 390, height: 844, mobile: true },
];

for (const vp of VIEWPORTS) {
  test.describe(vp.name, () => {
    test.use({ viewport: { width: vp.width, height: vp.height }, isMobile: vp.mobile, hasTouch: vp.mobile, contextOptions: { reducedMotion: "reduce" } });

    test("Buch passt ins Fenster, kein horizontaler Überlauf", async ({ page }) => {
      const book = await openCatalog(page, vp.mobile);
      await book.getByRole("button", { name: "Buchstabe K" }).click();
      await expect(book.getByRole("button", { name: /^Kraftklub/ })).toBeVisible();
      const pages = book.locator(".cat-book");
      const box = await pages.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x, "links im Bild").toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width, "rechts im Bild").toBeLessThanOrEqual(vp.width);
      expect(box!.y + box!.height, "unten im Bild").toBeLessThanOrEqual(vp.height);
      await expect(book.locator(vp.mobile ? ".cat-page.is-single" : ".cat-page.is-right")).toBeVisible();
      await book.getByRole("button", { name: /^Kraftklub/ }).click();
      await expect(page.getByRole("dialog", { name: "Kraftklub – Details" })).toBeInViewport();
      await screenshot(page, `${vp.name}-karte`);
      await expectNoHorizontalOverflow(page, vp.name);
    });
  });
}
