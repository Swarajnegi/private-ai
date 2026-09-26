/** Offline browser regression for the JARVIS UI; fixtures never touch the real mind. */
const {
  chromium,
} = require("../js-development/jarvis_core/serve/frontend/node_modules/playwright");
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
    {
      role: "user",
      content: "An older conversation",
      ts: "2025-06-17T11:33:00Z",
    },
    {
      role: "assistant",
      content: "An earlier thought.",
      ts: "2025-06-17T11:34:00Z",
    },
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
let voiceReady = false;
let voiceTranscriptions = 0;
let voiceSyntheses = 0;
const voiceWav = Buffer.alloc(44 + 8820);
voiceWav.write("RIFF");
voiceWav.writeUInt32LE(voiceWav.length - 8, 4);
voiceWav.write("WAVEfmt ", 8);
voiceWav.writeUInt32LE(16, 16);
voiceWav.writeUInt16LE(1, 20);
voiceWav.writeUInt16LE(1, 22);
voiceWav.writeUInt32LE(22050, 24);
voiceWav.writeUInt32LE(44100, 28);
voiceWav.writeUInt16LE(2, 32);
voiceWav.writeUInt16LE(16, 34);
voiceWav.write("data", 36);
voiceWav.writeUInt32LE(8820, 40);
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
    if (healthOffline) {
      res.statusCode = 503;
      return json({ error: "Fixture unavailable" });
    }
  if (url.pathname === "/v1/health")
    return json({
      ok: true,
      busy: false,
      pid: 1,
      uptime_seconds: 7260,
      requests_served: requests.length,
      jobs,
    });
  if (url.pathname === "/v1/models")
    return json({
      models: [
        { id: "openrouter/free", name: "Free router", free: true },
        {
          id: "test/paid",
          name: "Paid fixture",
          free: false,
          cost_input_1m: 1,
          cost_output_1m: 3,
        },
      ],
    });
  if (url.pathname === "/v1/voice/capabilities")
    return json({ transcription: voiceReady, synthesis: voiceReady });
  if (url.pathname === "/v1/voice/transcribe") {
    voiceTranscriptions++;
    return json({ text: "Voice fixture question", local: true });
  }
  if (url.pathname === "/v1/voice/synthesize") {
    voiceSyntheses++;
    return json({ audio: voiceWav.toString("base64"), local: true });
  }
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
    if (data.question === "A new thought")
      await new Promise((resolve) => setTimeout(resolve, 1800));
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
  await new Promise((resolve) =>
    server.listen(
      Number(process.env.JARVIS_UI_FIXTURE_PORT || 0),
      "127.0.0.1",
      resolve,
    ),
  );
  if (process.env.JARVIS_UI_FIXTURE_PORT) {
    console.log("Fixture on port " + server.address().port);
    return;
  }
  const browser = await chromium.launch({
    channel: "msedge",
    headless: true,
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
      "--autoplay-policy=no-user-gesture-required",
    ],
  });
  try {
    const page = await browser.newPage({
        viewport: { width: 1536, height: 864 },
      }),
      errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("http://127.0.0.1:" + server.address().port);
    await page.locator("#token").fill("test-token");
    await page.locator("#connection-form button[type=submit]").click();
    await page.waitForFunction(() =>
      document.querySelector("#connection").textContent.includes("CONNECTED"),
    );
    await page.locator("#model-picker").click();
    assert.equal(await page.locator(".model-option").count(), 2);
    await page.locator("#model-search").fill("paid");
    await page.locator(".model-option").click();
    assert.match(
      await page.locator("#model-label").innerText(),
      /Paid fixture/,
    );
    await page.locator("#nav-history").click();
    assert.match(await page.locator(".session").first().innerText(), /named/);
    await page.locator(".session").first().click();
    assert.match(
      await page.locator(".message.assistant").innerText(),
      /FINAL MARKER — 完整回答 🧠/,
    );
    assert.equal(await page.evaluate(() => Boolean(window.injected)), false);
    await page
      .locator(".message.assistant button")
      .filter({ hasText: "Raw" })
      .click();
    assert.equal(
      await page.locator(".message.assistant .message-content").innerText(),
      longAnswer,
    );
    await page
      .locator(".message.assistant button")
      .filter({ hasText: "Raw" })
      .click();
    assert.equal(await page.locator(".message-content script").count(), 0);
    await page.locator("#prompt").fill("A new thought");
    await page.locator("#send").click();
    await page.waitForFunction(() => !document.querySelector("#send").disabled);
    assert.equal(requests.at(-1).model, "test/paid");
    assert.equal(requests.at(-1).session, "named-session");
    assert.equal(await page.locator(".message.assistant").count(), 2);
    assert.match(
      await page.locator(".message.assistant").last().innerText(),
      /FINAL MARKER/,
    );
    await page.locator("#prompt").fill("SIMULATE BUSY");
    await page.locator("#send").click();
    await page.waitForFunction(() => !document.querySelector("#send").disabled);
    assert.match(await page.locator("#notice").innerText(), /busy/);
    assert.equal(await page.locator("#prompt").inputValue(), "SIMULATE BUSY");
    await page.locator("#nav-core").click();
    await page.locator("#motion").click();
    assert.equal(
      await page.locator("#motion").getAttribute("aria-pressed"),
      "true",
    );
    await page.locator("#motion").click();
    fs.mkdirSync(screenshotRoot, { recursive: true });
    for (const [width, height] of [
      [1920, 1080],
      [1536, 864],
      [1280, 720],
      [1100, 700],
    ]) {
      await page.setViewportSize({ width, height });
      await page.waitForTimeout(500);
      const boxes = await page.evaluate(() =>
        ["universe", "dock"].map((id) => {
          const b = document.getElementById(id).getBoundingClientRect();
          return { x: b.x, y: b.y, right: b.right, bottom: b.bottom };
        }),
      );
      for (const b of boxes) {
        assert(
          b.x >= 0 &&
            b.y >= 0 &&
            b.right <= width + 1 &&
            b.bottom <= height + 1,
          JSON.stringify({ width, height, b }),
        );
      }
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
      );
      await page.screenshot({
        path: path.join(screenshotRoot, "observatory-" + width + ".png"),
      });
    }
    await page.setViewportSize({ width: 1536, height: 864 });
    await page.locator("#nav-chat").click();
    await page.waitForTimeout(900);
    await page.locator('#prompt').fill('A longer thought\n'.repeat(30));
    await page.waitForTimeout(200);
    assert(await page.evaluate(()=>document.querySelector('#conversation').getBoundingClientRect().bottom < document.querySelector('#dock').getBoundingClientRect().top),'Growing composer must not cover conversation');
    await page.locator('#prompt').fill('');
    const exportEvent=page.waitForEvent('download');
    await page.locator('#export').click();
    const download=await exportEvent;
    const exported=fs.readFileSync(await download.path(),'utf8');
    assert(exported.includes('FINAL MARKER — 完整回答 🧠'));
    await page.screenshot({
      path: path.join(screenshotRoot, "conversation.png"),
    });
    await page.locator("#nav-system").click();
    healthOffline = true;
    await page.waitForFunction(
      () =>
        document.querySelector("#connection").textContent === "DISCONNECTED",
      {},
      { timeout: 20000 },
    );
    assert.match(
      await page.locator("#system-status").innerText(),
      /No current telemetry/,
    );
    healthOffline = false;
    await page.waitForFunction(
      () =>
        document.querySelector("#connection").textContent.includes("CONNECTED"),
      {},
      { timeout: 20000 },
    );
    await page.keyboard.press("Escape");
    await page.locator("#mic").click();
    await page.waitForFunction(() =>
      document
        .querySelector("#state")
        .textContent.includes("Install local voice"),
    );
    assert.equal(
      await page.evaluate(() => Boolean(window.speechSynthesis?.speaking)),
      false,
    );
    voiceReady = true;
    const beforeVoice = requests.length;
    await page.locator("#mic").click();
    await page.waitForFunction(
      () => document.querySelector("#universe").dataset.state === "listening",
    );
    await page.waitForTimeout(250);
    await page.locator("#mic").click();
    await page.waitForFunction(
      () =>
        document.querySelector("#prompt").value === "Voice fixture question",
    );
    assert.equal(
      requests.length,
      beforeVoice,
      "Push-to-talk transcript requires Send",
    );
    await page.locator("#handsfree").click();
    await page.waitForFunction(
      () => document.querySelector("#universe").dataset.state === "listening",
    );
    await page.waitForTimeout(250);
    await page.locator("#mic").click();
    await page.waitForFunction(
      () => document.querySelector("#universe").dataset.state === "speaking",
    );
    await page.waitForFunction(
      () => document.querySelector("#universe").dataset.state === "listening",
      {},
      { timeout: 20000 },
    );
    await page.locator("#voice-stop").click();
    assert.equal(requests.length, beforeVoice + 1);
    assert(
      voiceTranscriptions >= 2 && voiceSyntheses > 1,
      "Long answer uses consecutive local speech chunks",
    );
    assert.equal(await page.locator("#voice-stop").isVisible(), false);
    assert.deepEqual(errors, []);
    console.log(
      "PASS: auth, paid/free models, newest-first history, full Markdown/raw/XSS, split SSE, session continuity, busy recovery, motion, four desktop sizes, health recovery, local voice fallback, synthetic microphone transcript review, hands-free response/speech/relisten/stop.",
    );
    console.log("Screenshots: " + screenshotRoot);
  } finally {
    await browser.close();
    server.close();
  }
})().catch((e) => {
  console.error(e);
  server.close();
  process.exitCode = 1;
});
