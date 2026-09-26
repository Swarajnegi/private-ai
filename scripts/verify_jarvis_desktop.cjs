// Reads the live hearth and saved history; never submits a model request.
const {
  chromium,
} = require("../js-development/jarvis_core/serve/frontend/node_modules/playwright");
const fs = require("node:fs"),
  path = require("node:path"),
  assert = require("node:assert/strict");
(async () => {
  const dir = path.resolve("artifacts/jarvis-ui");
  fs.mkdirSync(dir, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    const page = await browser.newPage({
        viewport: { width: 1536, height: 864 },
      }),
      errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const credential = fs
      .readFileSync("jarvis_data/.hearth_token", "utf8")
      .trim();
    await page.addInitScript(
      (t) => sessionStorage.setItem("jarvis_hearth_token", t),
      credential,
    );
    await page.goto("http://127.0.0.1:8756/");
    await page.waitForFunction(() =>
      /CONNECTED|ATTENTION/.test(
        document.querySelector("#connection").textContent,
      ),
    );
    await page.waitForTimeout(2000);
    await page.screenshot({ path: path.join(dir, "live-core.png") });
    await page.locator("#model-picker").click();
    const count = await page.locator(".model-option").count();
    assert(count > 1);
    await page.screenshot({ path: path.join(dir, "live-models.png") });
    await page.keyboard.press("Escape");
    await page.locator("#nav-history").click();
    const sessions = await page.locator(".session").count();
    assert(sessions > 0);
    await page.locator(".session").first().click();
    await page.locator(".message").first().waitFor();
    await page.waitForTimeout(900);
    await page.screenshot({ path: path.join(dir, "live-conversation.png") });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    await page.locator("#nav-system").click();
    await page.screenshot({ path: path.join(dir, "live-health.png") });
    const voice = await page.evaluate(async (t) => {
      const r = await fetch("/v1/voice/capabilities", {
        headers: { Authorization: "Bearer " + t },
      });
      return r.json();
    }, credential);
    assert(voice.local && voice.transcription && voice.synthesis);
    assert.deepEqual(errors, []);
    console.log(
      JSON.stringify({
        models: count,
        sessions,
        voice: "local engines ready",
        errors: errors.length,
        readOnly: true,
      }),
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e.message);
  process.exitCode = 1;
});
