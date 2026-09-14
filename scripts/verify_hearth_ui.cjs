/** Offline browser regression for the JARVIS UI; fixtures never touch the real mind. */
const { chromium } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");
const http = require("node:http");
const assert = require("node:assert/strict");
const os = require("node:os");
const root = path.resolve(__dirname, "..");
const ui = path.join(root, "js-development/jarvis_core/serve/ui");
const screenshotRoot =
  process.env.JARVIS_UI_SCREENSHOTS ||
  fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-ui-"));
const longAnswer =
  "# Complete response\n\n" +
  "A durable conversation preserves every detail. ".repeat(220) +
  '\n\n| Decision | Status |\n| --- | --- |\n| Preserve complete answers | Done |\n\n```python\n# preserve **literal** code\nprint("<hello>")\n```\n\n' +
  "<script>window.injected = true</script>\n\n[unsafe](javascript:alert(1))\n\nFINAL MARKER — 完整回答 🧠";
let conversations = {
  "older-session": [
    { role: "user", content: "An older conversation", ts: "2025-06-17T11:33:00Z" },
    { role: "assistant", content: "An earlier thought.", ts: "2025-06-17T11:34:00Z" },
  ],
  "named-session": [
    {
      role: "user",
      content: "A named conversation",
      ts: new Date().toISOString(),
    },
    { role: "assistant", content: longAnswer, ts: new Date().toISOString() },
  ],
};
let requests = [];
let healthOffline = false;
const jobs = [
  "consolidate",
  "refresh_profile",
  "reindex_memory",
  "ingest_codex",
  "reconcile_codex_memory",
  "refresh_digest",
].map((name) => ({ name, status: "ok", last_run_age_s: 320 }));
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  if (
    url.pathname.startsWith("/v1/") &&
    req.headers.authorization !== "Bearer test-token"
  ) {
    res.writeHead(403, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "bad token" }));
    return;
  }
  const json = (value) => {
    res.setHeader("Content-Type", "application/json");
    res.end(JSON.stringify(value));
  };
  if (url.pathname === "/v1/health")
    if (healthOffline) { res.statusCode = 503; return json({error: "Fixture unavailable"}); }
  if (url.pathname === "/v1/health")
    return json({
      ok: true,
      busy: false,
      pid: 1,
      uptime_seconds: 7260,
      requests_served: requests.length,
      jobs,
    });
  if (url.pathname === "/v1/auth/verify") return json({ ok: true });
  if (url.pathname === "/v1/sessions")
    return json({
      sessions: Object.entries(conversations).map(([session_id, messages]) => ({
        session_id,
        title: messages[0].content,
        first_prompt: messages[0].content,
        turn_count: messages.length,
        latest_ts: messages.at(-1).ts,
        mtime: Date.now() / 1000,
      })),
    });
  if (url.pathname.startsWith("/v1/sessions/"))
    return json({
      messages:
        conversations[decodeURIComponent(url.pathname.split("/").pop())] || [],
    });
  if (url.pathname === "/v1/ask") {
    let body = "";
    for await (const chunk of req) body += chunk;
    const data = JSON.parse(body);
    requests.push(data);
    if (data.question === "SIMULATE BUSY") {
      res.statusCode = 409;
      return json({ error: "hearth is busy with another question" });
    }
    conversations[data.session] ||= [];
    conversations[data.session].push(
      { role: "user", content: data.question },
      { role: "assistant", content: longAnswer },
    );
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    if (data.question === "A new thought") await new Promise(resolve => setTimeout(resolve, 1800));
    // Deliberately split event headers, JSON, and the multi-byte Unicode tail.
    for (const piece of [
      "eve",
      "nt: log\r\n",
      'data: {"line":"  brain : test/fixture"}\r',
      "\n\r\n",
      "event: ans",
      "wer\n",
    ]) {
      res.write(piece);
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
    const answer = Buffer.from(
      `data: ${JSON.stringify({ ok: true, answer: longAnswer, confidence: 0, verdict: "ESCALATE", ledger: { model: "test/fixture", spend_usd: 0 } })}\n\n`,
    );
    for (let i = 0; i < answer.length; i += 127) {
      res.write(answer.subarray(i, i + 127));
    }
    res.end();
    return;
  }
  const file =
    url.pathname === "/"
      ? path.join(ui, "index.html")
      : path.join(ui, url.pathname.replace("/ui/", ""));
  if (!file.startsWith(ui) || !fs.existsSync(file)) {
    res.statusCode = 404;
    res.end();
    return;
  }
  res.setHeader(
    "Content-Type",
    file.endsWith(".css")
      ? "text/css"
      : file.endsWith(".js")
        ? "application/javascript"
        : "text/html",
  );
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise((resolve) => server.listen(Number(process.env.JARVIS_UI_FIXTURE_PORT || 0), "127.0.0.1", resolve));
  if (process.env.JARVIS_UI_FIXTURE_PORT) {
    console.log(`Isolated UI fixture ready on http://127.0.0.1:${server.address().port}; token: test-token. No real data or model calls.`);
    return;
  }
  const browser = await chromium.launch({
    channel: process.env.JARVIS_BROWSER_CHANNEL || (process.platform === "win32" ? "msedge" : undefined),
    headless: true,
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1000 },
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("console", message => {
      if (/JARVIS core:|Hologram renderer:/.test(message.text())) errors.push(message.text());
    });
    const base = `http://127.0.0.1:${server.address().port}`;
    await page.goto(base);
    await page.locator("#settings[open]").waitFor();
    await page.locator("#token").fill("wrong");
    await page.locator(".connect-button").click();
    await page
      .getByText("Connection token is missing or invalid.", { exact: false })
      .waitFor();
    await page.locator("#token").fill("test-token");
    await page.locator(".connect-button").click();
    await page.locator(".session").first().waitFor();
    assert.match(await page.locator(".session").first().textContent(), /A named conversation/);
    assert.equal(await page.locator("#inspector").isVisible(), false);
    await page.locator('#model-picker').click();
    assert.ok(await page.locator('.model-option').count() > 15, 'Free and paid choices are present');
    await page.locator('#model-search').fill('claude');
    assert.ok(await page.locator('.model-option').count() >= 2);
    await page.screenshot({path: path.join(screenshotRoot, 'models-desktop.png')});
    const chosen = await page.locator('.model-option small').first().textContent();
    await page.locator('#model-search').press('ArrowDown');
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('#model').inputValue(), chosen);
    await page.reload();
    assert.equal(await page.locator('#model').inputValue(), chosen, 'Selection persists after reload');
    await page.locator('#model-picker').click();
    await page.locator('#model-search').fill('openrouter/free');
    await page.locator('.model-option').click();
    await page.getByRole("button", {name: "Pause core animation", exact: true}).click();
    assert.equal(await page.locator("#motion-toggle").getAttribute("aria-pressed"), "true");
    await page.getByRole("button", {name: "Play core animation", exact: true}).click();
    await page.waitForTimeout(3400);
    assert.equal(await page.locator(".living-core.core-fallback").count(), 0, "The actual hologram must render, not just its fallback");
    const core = page.locator(".living-core");
    const moving = await core.screenshot();
    await page.waitForTimeout(150);
    assert.ok(!(await core.screenshot()).equals(moving), "Hologram geometry must animate");
    await page.getByRole("button", {name: "Pause core animation", exact: true}).click();
    const frozen = await core.screenshot();
    await page.waitForTimeout(150);
    assert.ok((await core.screenshot()).equals(frozen), "Pause must stop every rendered signal");
    await page.emulateMedia({reducedMotion: "reduce"});
    await page.getByRole("button", {name: "Play core animation", exact: true}).waitFor();
    assert.equal(await page.evaluate(() => window.JarvisCore.paused), true);
    await page.emulateMedia({reducedMotion: "no-preference"});
    await page.getByRole("button", {name: "Pause core animation", exact: true}).waitFor();
    await core.evaluate(canvas => {
      window.coreRecovery = canvas.getContext("webgl").getExtension("WEBGL_lose_context");
      window.coreRecovery.loseContext();
    });
    await page.locator(".living-core.core-fallback").waitFor();
    await page.screenshot({path: path.join(screenshotRoot, "core-fallback.png")});
    await page.evaluate(() => window.coreRecovery.restoreContext());
    await page.waitForFunction(() => !document.querySelector(".living-core").classList.contains("core-fallback"));
    await page.screenshot({
      path: path.join(screenshotRoot, "home-desktop.png"),
    });
    await page.locator(".session").first().click();
    await page.getByText("FINAL MARKER", { exact: false }).waitFor();
    assert.equal(await page.locator(".message.assistant").count(), 1);
    assert.equal(await page.locator(".message-content table").count(), 1);
    assert.equal(await page.locator('a[href^="javascript:"]').count(), 0);
    assert.equal(await page.evaluate(() => window.injected), undefined);
    assert.match(
      await page.locator("pre code").textContent(),
      /\*\*literal\*\*/,
    );
    await page.getByRole("button", { name: "Raw", exact: true }).click();
    assert.equal(
      await page.locator(".message-content.raw").textContent(),
      longAnswer,
    );
    await page.reload();
    await page.getByText("FINAL MARKER", { exact: false }).waitFor();
    await page.locator("#new-chat").click();
    await page.locator("#prompt").fill("A new thought");
    await page.locator("#send").click();
    await page.locator("#working:not([hidden])").waitFor();
    await page.waitForTimeout(500);
    assert.equal(await page.locator(".thinking-core.core-fallback").count(), 0);
    await page.screenshot({path: path.join(screenshotRoot, "thinking-desktop.png")});
    await page.getByRole("button", { name: "Raw", exact: true }).waitFor();
    await page.getByRole("button", { name: "Raw", exact: true }).click();
    assert.equal(
      await page.locator(".message-content.raw").textContent(),
      longAnswer,
    );
    assert.match(
      await page.locator(".message-meta").textContent(),
      /0% confidence/,
    );
    await page.locator("#prompt").fill("Follow up in this same conversation");
    await page.locator("#send").click();
    await page.waitForFunction(
      () => document.querySelectorAll(".message.assistant").length === 2,
    );
    assert.equal(requests[0].session, requests[1].session);
    assert.equal(requests[0].allow_all, false);
    const downloadPromise = page.waitForEvent("download");
    await page.locator("#export").click();
    const download = await downloadPromise;
    const downloaded = await download.path();
    assert.match(
      fs.readFileSync(downloaded, "utf8"),
      /FINAL MARKER — 完整回答 🧠/,
    );
    await page.locator("#prompt").fill("SIMULATE BUSY");
    await page.locator("#send").click();
    await page
      .locator("#notice")
      .filter({ hasText: "hearth is busy" })
      .waitFor();
    assert.equal(await page.locator("#prompt").inputValue(), "SIMULATE BUSY");
    await page.locator("#search").fill("nomatch");
    assert.equal(await page.locator(".session").count(), 0);
    await page.locator("#search").fill("");
    await page.locator("#new-chat").click();
    await page.locator("#prompt").fill("A draft to keep");
    await page.reload();
    assert.equal(await page.locator("#prompt").inputValue(), "A draft to keep");
    await page.locator("#prompt").fill("");
    for (const viewport of [{width:1920,height:900},{width:1536,height:864},{width:1280,height:720},{width:1100,height:700}]) {
      await page.setViewportSize(viewport);
      await page.waitForTimeout(300);
      const layout = await page.evaluate(() => {
        const r = document.querySelector('.living-core').getBoundingClientRect(), m = document.querySelector('#messages');
        return {square: Math.abs(r.width-r.height)<1, overflow:document.documentElement.scrollWidth>innerWidth, welcomeOverflow:m.scrollHeight>m.clientHeight+2};
      });
      assert.deepEqual(layout, {square:true,overflow:false,welcomeOverflow:false}, JSON.stringify(viewport));
      await page.screenshot({path:path.join(screenshotRoot, `home-${viewport.width}.png`)});
    }
    await page.setViewportSize({width:1536,height:864});
    jobs[0].status = 'FAILED rc=1';
    await page.waitForFunction(() => document.body.dataset.connection === 'degraded');
    await page.locator('#inspector-button').click();
    assert.equal(await page.locator('.job.error').count(), 1);
    await page.screenshot({path: path.join(screenshotRoot, 'health-degraded.png')});
    healthOffline = true;
    await page.waitForFunction(() => document.body.dataset.connection === 'offline');
    assert.match(await page.locator('.pulse-caption').textContent(), /FAILED/);
    healthOffline = false; jobs[0].status = 'ok';
    await page.waitForFunction(() => document.body.dataset.connection === 'online');
    await page.screenshot({path: path.join(screenshotRoot, 'health-live.png')});
    await page.locator('#close-inspector').click();
    await page.locator(".session").first().click();
    await page.getByText("FINAL MARKER", { exact: false }).first().waitFor();
    await page.screenshot({
      path: path.join(screenshotRoot, "chat-desktop.png"),
    });
    assert.deepEqual(errors, []);
    console.log(
      "PASS: authentication, complete Markdown, XSS handling, long history, chunked SSE, Unicode, session continuity, zero confidence, export, busy recovery, search, drafts, keyboard model picker, model persistence, spherical desktop layout, hologram motion/pause/context recovery, measured health/degraded/offline/reconnect states.",
    );
    console.log(`Screenshots: ${screenshotRoot}`);
    if (process.env.JARVIS_UI_LIVE === "1") {
      const live = await browser.newPage({
        viewport: { width: 1440, height: 1000 },
      });
      const token = fs
        .readFileSync(path.join(root, "jarvis_data/.hearth_token"), "utf8")
        .trim();
      await live.addInitScript(
        (value) => sessionStorage.setItem("jarvis_hearth_token", value),
        token,
      );
      await live.goto("http://127.0.0.1:8756");
      await live.locator(".session").first().waitFor();
      await live.waitForTimeout(3400);
      console.log(
        "Live saved sessions displayed:",
        await live.locator(".session").count(),
      );
      await live.screenshot({
        path: path.join(screenshotRoot, "live-desktop.png"),
      });
      await live.locator(".session").first().click();
      await live.locator(".message").first().waitFor();
      console.log(
        "Live conversation messages displayed:",
        await live.locator(".message").count(),
      );
      await live.screenshot({
        path: path.join(screenshotRoot, "live-chat.png"),
        animations: "disabled",
      });
    }
  } finally {
    await browser.close();
    server.close();
  }
})().catch((error) => {
  console.error(error);
  server.close();
  process.exitCode = 1;
});
