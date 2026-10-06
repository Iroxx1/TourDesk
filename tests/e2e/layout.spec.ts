// Layout with a long tour (34 dates, as reported for Nena): the expanded tile uses its width
// with two columns, and nothing ever scrolls horizontally – tile, artist window and agenda,
// on desktop and mobile. Runs after the user journey (project dependency in
// playwright.config.ts) and gives its user the tour via fixtures/long_tour.py.
// TOURDESK_E2E_SCREENSHOTS=<directory> additionally saves screenshots of every check.
import { execFileSync } from "node:child_process";
import path from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { USER, login } from "./helpers";

const ARTIST = "Die Tourneeband";
const DATES = 34;
const SCREENSHOTS = process.env.TOURDESK_E2E_SCREENSHOTS;

const VIEWPORTS = [
  { name: "1280x800", width: 1280, height: 800, mobile: false },
  { name: "1920x1080", width: 1920, height: 1080, mobile: false },
  { name: "390x844", width: 390, height: 844, mobile: true },
];

// the tests are independent (each logs in by itself), so a failure does not skip the others
test.beforeAll(() => {
  const root = path.resolve(__dirname, "../..");
  const python = path.join(process.env.TOURDESK_VENV ?? path.join(root, ".venv"), "bin", "python");
  const fixture = path.join(__dirname, "fixtures", "long_tour.py");
  execFileSync(python, [fixture, "--user", USER.username, "--artist", ARTIST, "--dates", String(DATES)], { stdio: "inherit" });
});

interface Metrics {
  index: number;
  scrollWidth: number;
  clientWidth: number;
  scrollHeight: number;
  clientHeight: number;
  /** descendants sticking out on the right (not clipped by an ancestor) – names the culprit */
  culprits: string[];
}

function metrics(target: Locator): Promise<Metrics[]> {
  return target.evaluateAll((els) =>
    els.map((el, index) => {
      const culprits: string[] = [];
      if (el.scrollWidth > el.clientWidth) {
        const right = el.getBoundingClientRect().left + el.clientLeft + el.clientWidth;
        const clipped = (node: Element | null) => {
          for (let n = node; n && n !== el; n = n.parentElement) if (getComputedStyle(n).overflowX !== "visible") return true;
          return false;
        };
        for (const child of el.querySelectorAll("*")) {
          const r = child.getBoundingClientRect();
          if (r.width > 0 && r.right > right + 0.5 && !clipped(child.parentElement)) {
            const cls = (child.getAttribute("class") ?? "").trim().split(/\s+/).filter(Boolean).join(".");
            culprits.push(`${child.tagName.toLowerCase()}${cls ? "." + cls : ""} +${Math.round(r.right - right)}px`);
          }
        }
      }
      return { index, scrollWidth: el.scrollWidth, clientWidth: el.clientWidth, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight, culprits: culprits.slice(0, 6) };
    }),
  );
}

/** scrollWidth <= clientWidth for every element of every selector (soft: report all at once). */
async function expectNoHorizontalOverflow(page: Page, label: string, selectors: string[]) {
  for (const selector of selectors) {
    const found = await metrics(page.locator(selector));
    expect.soft(found.length, `${label}: ${selector} nicht gefunden`).toBeGreaterThan(0);
    for (const m of found) {
      const culprits = m.culprits.length ? ` – ragt heraus: ${m.culprits.join(", ")}` : "";
      console.log(`${label} ${selector}[${m.index}]: scroll ${m.scrollWidth}×${m.scrollHeight}, client ${m.clientWidth}×${m.clientHeight}${culprits}`);
      expect.soft(m.scrollWidth, `${label}: ${selector}[${m.index}] läuft horizontal über${culprits}`).toBeLessThanOrEqual(m.clientWidth);
    }
  }
}

/** Saves a screenshot of the viewport (and of `detail`) when TOURDESK_E2E_SCREENSHOTS is set. */
async function screenshot(page: Page, name: string, detail?: Locator) {
  if (!SCREENSHOTS) return;
  await page.screenshot({ path: path.join(SCREENSHOTS, `${name}.png`) });
  if (detail) await detail.screenshot({ path: path.join(SCREENSHOTS, `${name}-detail.png`) });
}

async function box(target: Locator) {
  const b = await target.boundingBox();
  expect(b).not.toBeNull();
  return b!;
}

for (const vp of VIEWPORTS) {
  test.describe(vp.name, () => {
    test.use({ viewport: { width: vp.width, height: vp.height }, isMobile: vp.mobile, hasTouch: vp.mobile });

    test("aufgeklappte Kachel: Platz genutzt, kein horizontaler Überlauf", async ({ page }) => {
      await login(page, USER.username, USER.password);
      const tile = page.locator(".tile", { hasText: ARTIST });
      await tile.getByRole("button", { name: "Gesamte Tour anzeigen" }).click();
      const tour = tile.locator(".tile-tour");
      const lines = tour.locator(".event-line");
      await expect(lines).toHaveCount(DATES);
      await expect(tile.locator(".tile-mine .event-line").first()).toBeVisible();
      await tour.evaluate((el) => el.scrollIntoView({ block: "start" }));
      await screenshot(page, `${vp.name}-kachel`, tour);

      // .desktop-area is the scroll container of the desktop (the swipeable chip row of the phone
      // layout deliberately reaches into its padding, so the inner .desktop-main is not checked)
      await expectNoHorizontalOverflow(page, `${vp.name} Desktop`, [".desktop-area", ".tile-events"]);
      const list = (await metrics(tour.locator(".tile-events")))[0];
      const [first, second, middle] = [await box(lines.nth(0)), await box(lines.nth(1)), await box(lines.nth(DATES / 2))];
      expect(second.y, "chronologisch von oben nach unten").toBeGreaterThan(first.y);
      if (vp.mobile) {
        expect(Math.abs(middle.x - first.x), "mobil einspaltig").toBeLessThan(1);
      } else {
        // the expanded tile spans two grid columns: two columns of dates, the second one starts
        // at the top with the 18th date …
        expect(middle.x, "zweite Spalte").toBeGreaterThan(first.x + first.width / 2);
        expect(Math.abs(middle.y - first.y), "zweite Spalte beginnt oben").toBeLessThan(2);
        // … and all 34 dates fit without an inner scrollbar
        expect(list.scrollHeight, "kein vertikaler Scrollbalken in der Kachel").toBeLessThanOrEqual(list.clientHeight);
        await expect(lines.nth(DATES - 1)).toBeInViewport({ ratio: 1 });
      }
    });

    test("Gesamte Tour im Künstlerfenster ohne horizontalen Überlauf", async ({ page }) => {
      await login(page, USER.username, USER.password);
      await page.getByRole("button", { name: `${ARTIST} öffnen` }).click();
      const win = page.locator(".window:not(.is-hidden)", { has: page.locator(".artist-app") });
      await win.getByRole("tab", { name: /Gesamte Tour/ }).click();
      await expect(win.locator(".event-row")).toHaveCount(DATES);
      await screenshot(page, `${vp.name}-kuenstlerfenster`);
      await expectNoHorizontalOverflow(page, `${vp.name} Künstlerfenster`, [
        ".window:not(.is-hidden) .window-body",
        ".window:not(.is-hidden) .event-list",
      ]);
    });

    test("Agenda ohne horizontalen Überlauf", async ({ page }) => {
      await login(page, USER.username, USER.password);
      await page.locator(vp.mobile ? ".mobile-nav-btn" : ".desktop-icon", { hasText: "Termine" }).click();
      const win = page.locator(".window:not(.is-hidden)", { has: page.locator(".agenda-app") });
      await win.getByRole("radio", { name: "Alle Termine meiner Künstler" }).click();
      await expect(win.locator(".event-row", { hasText: "Mehrzweckhalle am Stadtpark" })).toBeVisible();
      await screenshot(page, `${vp.name}-agenda`);
      await expectNoHorizontalOverflow(page, `${vp.name} Agenda`, [
        ".window:not(.is-hidden) .window-body",
        ".window:not(.is-hidden) .event-list",
      ]);
    });
  });
}
