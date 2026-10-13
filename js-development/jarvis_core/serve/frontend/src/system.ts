/**
 * System presentation — readable live summaries with complete diagnostics.
 * LAYER: Body. Keyed rows survive refresh so focus and disclosures stay put.
 */
import { health, voiceCapabilities, type Health, type JobStatus,
  type PipelineReport, type VoiceCapabilities } from "./api";

type Tone = "neutral" | "warning" | "danger";
type Issue = { name: string; summary: string; state: string; tone: Tone };

export function readableName(name: string): string {
  const words = name.replace(/[_:/.-]+/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function describeIssue(check: string, detail: string): Issue {
  if (check.startsWith("backlog")) return {
    name: check.includes(":") ? `Parse backlog · ${check.split(":")[1]}` : "Parse backlog",
    summary: "Captured turns are waiting for review.", state: "Pending", tone: "danger",
  };
  if (check.startsWith("projection:")) return {
    name: check.includes("jarvis_memory") ? "Memory index" : readableName(check.slice(11)),
    summary: "This projection is behind the knowledge base.", state: "Behind", tone: "warning",
  };
  if (check.startsWith("job:")) {
    const failed = /failure|failed|rc=|never succeeded|crashed/i.test(detail);
    return { name: readableName(check.slice(4)),
      summary: failed ? "A scheduled run failed. Review its diagnostic output." :
        "The last successful run is outside the expected window.",
      state: failed ? "Failed" : "Overdue", tone: "danger" };
  }
  if (check === "clock") return { name: "Capture freshness",
    summary: "The scheduled clock is outside its expected activity window.",
    state: "Overdue", tone: "danger" };
  if (check.startsWith("corpus")) return { name: "Training corpus freshness",
    summary: "Built training data needs review. Owner-paused maintenance remains paused.",
    state: "Needs review", tone: "warning" };
  return { name: readableName(check), summary: "This check needs attention. Open Details for the full report.",
    state: "Needs review", tone: "danger" };
}

export function jobPresentation(job: JobStatus): { label: string; tone: Tone } {
  if (job.paused) return { label: "Paused by owner", tone: "neutral" };
  const state = job.last_status ?? job.status ?? "Not reported";
  if ((job.consecutive_failures ?? 0) > 0 || /failed/i.test(state)) return { label: "Failed", tone: "danger" };
  if (state === "ok") return { label: "Completed", tone: "neutral" };
  if (state.startsWith("skipped")) return { label: "Skipped", tone: "neutral" };
  return { label: readableName(state), tone: "neutral" };
}

export function voicePresentation(voice: VoiceCapabilities | null): { label: string; tone: Tone } {
  if (!voice) return { label: "Not reported", tone: "neutral" };
  if (voice.error) return { label: voice.warm ? "Degraded" : "Unavailable", tone: "danger" };
  return { label: voice.warm ? "Available" : "Not loaded", tone: "neutral" };
}

function timeOfRun(timestamp?: number | null): string {
  if (!timestamp) return "Never run";
  const date = new Date(timestamp * 1000);
  return Number.isFinite(date.getTime()) ? date.toLocaleString([], {
    dateStyle: "medium", timeStyle: "short",
  }) : "Not reported";
}

function node<K extends keyof HTMLElementTagNameMap>(tag: K, className = "", text = ""): HTMLElementTagNameMap[K] {
  const result = document.createElement(tag);
  result.className = className;
  result.textContent = text;
  return result;
}

function disclosure(label: string): { el: HTMLDetailsElement; pre: HTMLPreElement } {
  const el = node("details", "diagnostic-details");
  el.append(node("summary", "link", label));
  const pre = node("pre", "diagnostic-output");
  el.append(pre);
  return { el, pre };
}

function cell(no: string, title: string, subtitle: string, wide = false): HTMLElement {
  const el = node("div", `cell${wide ? " cell-wide" : ""}`);
  el.append(node("span", "cell-no", no), node("h3", "", title), node("span", "cell-sub", subtitle));
  return el;
}

type IssueRow = {
  el: HTMLLIElement; name: HTMLElement; summary: HTMLElement; state: HTMLElement;
  details: ReturnType<typeof disclosure>;
};
type JobRow = {
  el: HTMLTableRowElement; name: HTMLElement; time: HTMLElement; state: HTMLElement;
  details: ReturnType<typeof disclosure>;
};

export class SystemView {
  private loading = false;
  private lastHealth: Health | null = null;
  private lastUpdated = "";
  private status: HTMLElement;
  private retry: HTMLButtonElement;
  private pipelineState: HTMLElement;
  private pipelineMessage = node("p", "", "Awaiting the first live report.");
  private issues = node("ul", "issue-list");
  private issueRows = new Map<string, IssueRow>();
  private diagnostics = disclosure("Show full diagnostic output");
  private backlog = node("p", "system-lines", "Not reported.");
  private hearth = node("p", "", "Not reported.");
  private warm = node("p", "", "Not reported.");
  private warmDetails = disclosure("Warm-up details");
  private voice = node("p", "", "Not reported.");
  private voiceDetails = disclosure("Voice details");
  private jobCount: HTMLElement;
  private jobBody = node("tbody");
  private jobRows = new Map<string, JobRow>();
  private showJobs = node("button", "link", "Show all jobs");
  private allJobs = false;
  private lastError = disclosure("Last request error");

  constructor(root: HTMLElement) {
    this.status = root.querySelector("#system-status")!;
    this.retry = root.querySelector("#system-retry")!;
    this.retry.addEventListener("click", () => void this.refresh());
    this.warmDetails.el.hidden = true;
    this.voiceDetails.el.hidden = true;
    this.showJobs.hidden = true;
    this.diagnostics.pre.textContent = "Awaiting live diagnostic data.";
    const pipeline = cell("01", "Pipeline health", "Not reported", true);
    pipeline.classList.add("pipeline-panel");
    this.pipelineState = pipeline.querySelector(".cell-sub")!;
    pipeline.append(this.pipelineMessage, this.issues, this.diagnostics.el);
    const backlog = cell("02", "Parse backlog", "Turns waiting for review");
    backlog.append(this.backlog);
    const hearth = cell("03", "Hearth", "Always-on process");
    hearth.append(this.hearth);
    const warm = cell("04", "Warm-up", "State + embeddings");
    warm.append(this.warm, this.warmDetails.el);
    const voice = cell("05", "Voice", "Ears → voice");
    voice.append(this.voice, this.voiceDetails.el);
    const jobs = cell("06", "On the clock", "Automated jobs", true);
    this.jobCount = jobs.querySelector(".cell-sub")!;
    const table = node("table", "job-table");
    table.setAttribute("aria-label", "Scheduled jobs");
    const head = node("thead");
    const row = node("tr");
    for (const label of ["Job", "Last run", "Status", "Details"]) {
      const th = node("th", "", label);
      th.scope = "col";
      row.append(th);
    }
    head.append(row);
    table.append(head, this.jobBody);
    const scroll = node("div", "job-table-scroll");
    scroll.append(table);
    this.showJobs.type = "button";
    this.showJobs.setAttribute("aria-expanded", "false");
    this.showJobs.addEventListener("click", () => {
      this.allJobs = !this.allJobs;
      if (this.lastHealth) this.paintJobs(this.lastHealth.jobs || []);
    });
    jobs.append(scroll, this.showJobs);
    const error = cell("07", "Last request error", "Most recent failure", true);
    error.hidden = true;
    error.append(this.lastError.el);
    this.lastError.el.dataset.panel = "request-error";
    root.querySelector("#system-grid")!.replaceChildren(pipeline, backlog, hearth, warm, voice, jobs, error);
  }

  async refresh(): Promise<void> {
    if (this.loading) return;
    this.loading = true;
    this.retry.setAttribute("aria-disabled", "true");
    this.retry.setAttribute("aria-busy", "true");
    const [report, voice] = await Promise.allSettled([health(), voiceCapabilities()]);
    try {
      if (report.status === "rejected") throw report.reason;
      this.lastHealth = report.value;
      this.lastUpdated = new Date().toLocaleTimeString([], { timeStyle: "short" });
      this.paint(report.value, voice.status === "fulfilled" ? voice.value : null);
      this.status.textContent = `Live state · updated ${this.lastUpdated}${voice.status === "rejected" ? " · voice state could not be read" : ""}`;
      this.status.classList.remove("bad");
      this.retry.hidden = false;
      this.retry.textContent = "Refresh";
    } catch (error) {
      this.status.textContent = `${this.lastHealth ? `Showing the previous report from ${this.lastUpdated}. ` : "Live state unavailable. "}` +
        `Could not refresh: ${(error as Error).message}`;
      this.status.classList.add("bad");
      this.retry.hidden = false;
      this.retry.textContent = "Retry";
    } finally {
      this.loading = false;
      this.retry.setAttribute("aria-disabled", "false");
      this.retry.setAttribute("aria-busy", "false");
    }
  }

  private paint(report: Health, voice: VoiceCapabilities | null): void {
    this.paintPipeline(report.pipeline ?? null);
    this.diagnostics.pre.textContent = JSON.stringify({ health: report, voice }, null, 2);
    const hosts = Object.entries(report.pipeline?.backlog || {});
    const total = hosts.reduce((sum, [, slot]) => sum + slot.pending, 0);
    this.backlog.textContent = hosts.length ? `${total} turns waiting for review\n` +
      hosts.map(([host, slot]) => `${host}: ${slot.pending} pending${slot.oldest_age_h != null ? ` · oldest ${(slot.oldest_age_h / 24).toFixed(1)} d` : ""}`).join("\n") :
      "No backlog data reported.";
    this.backlog.dataset.tone = report.pipeline?.breaches.some((issue) => issue.check.startsWith("backlog")) ? "danger" : "neutral";
    const hours = Math.floor(report.uptime_seconds / 3600);
    const minutes = Math.floor(report.uptime_seconds % 3600 / 60);
    this.hearth.textContent = `${report.ok ? "Online" : "Not ready"} · ${report.busy ? "working" : "idle"}\n` +
      `Up ${hours ? `${hours} h ` : ""}${minutes} min · ${report.requests_served} served · ${report.requests_rejected} refused`;
    const warm = report.warm;
    this.warm.textContent = !warm ? "Not reported" : `${readableName(warm.state)}\n` +
      (warm.error ? "Some components could not load. Open details for the failure." :
        warm.seconds != null ? `Loaded in ${warm.seconds} s.` : "No completed warm-up time reported.");
    this.warm.dataset.tone = warm?.error ? "danger" : "neutral";
    this.warmDetails.el.hidden = !warm?.error;
    this.warmDetails.pre.textContent = warm?.error || "";
    const voiceState = voicePresentation(voice);
    this.voice.textContent = `${voiceState.label}\n` + (voice?.warm ?
      `Whisper ${voice.stt_model} · ${voice.stt}\nVoice ${voice.voice} · ${voice.tts}` :
      voice?.error ? "The voice engine reported a failure. Open details for the reason." : "No loaded voice engine reported.");
    this.voice.dataset.tone = voiceState.tone;
    this.voiceDetails.el.hidden = !voice;
    this.voiceDetails.pre.textContent = JSON.stringify(voice, null, 2);
    this.paintJobs(report.jobs || []);
    this.lastError.el.parentElement!.hidden = !report.last_error;
    this.lastError.pre.textContent = report.last_error || "";
  }

  private paintPipeline(report: PipelineReport | null): void {
    this.pipelineState.textContent = !report ? "Not reported" : report.healthy === null ? "Computing" :
      report.healthy ? "Healthy" : `${report.breaches.length} checks need attention`;
    this.pipelineMessage.textContent = !report ? "The hearth has not supplied a pipeline report." :
      report.healthy === null ? report.status || "The first report is being built." :
      report.healthy ? "All reported pipeline checks pass." :
      !report.breaches.length ? "The report indicates a problem without individual diagnostic details." : "";
    this.pipelineMessage.hidden = !this.pipelineMessage.textContent;
    const seen = new Set<string>();
    const occurrences = new Map<string, number>();
    for (const breach of report?.breaches || []) {
      const occurrence = occurrences.get(breach.check) || 0;
      occurrences.set(breach.check, occurrence + 1);
      const key = `${breach.check}:${occurrence}`;
      seen.add(key);
      let row = this.issueRows.get(key);
      if (!row) {
        const details = disclosure("Details");
        const el = node("li", "issue-row");
        row = { el, name: node("span", "issue-name"), summary: node("span", "issue-description"),
          state: node("span", "issue-state"), details };
        el.append(row.name, row.summary, row.state, details.el);
        this.issueRows.set(key, row);
        this.issues.append(el);
      }
      const issue = describeIssue(breach.check, breach.detail);
      row.name.textContent = issue.name;
      row.summary.textContent = issue.summary;
      row.state.textContent = issue.state;
      row.state.dataset.tone = issue.tone;
      row.details.el.querySelector("summary")!.setAttribute("aria-label", `Details for ${issue.name}`);
      row.details.pre.textContent = `${breach.check}\n${breach.detail}`;
    }
    for (const [key, row] of this.issueRows) if (!seen.has(key)) {
      if (row.el.contains(document.activeElement)) this.retry.focus();
      row.el.remove();
      this.issueRows.delete(key);
    }
    this.issues.hidden = !seen.size;
  }

  private paintJobs(jobs: JobStatus[]): void {
    this.jobCount.textContent = jobs.length ? `${jobs.length} automated jobs` : "This hearth runs without scheduled jobs.";
    const seen = new Set<string>();
    for (const [index, job] of jobs.entries()) {
      seen.add(job.name);
      let row = this.jobRows.get(job.name);
      if (!row) {
        const details = disclosure("Details");
        row = { el: node("tr"), name: node("th"), time: node("td"), state: node("td"), details };
        (row.name as HTMLTableCellElement).scope = "row";
        const info = node("td");
        info.append(details.el);
        row.el.append(row.name, row.time, row.state, info);
        this.jobRows.set(job.name, row);
        this.jobBody.append(row.el);
      }
      row.el.hidden = !this.allJobs && index >= 5;
      row.name.textContent = readableName(job.name);
      row.time.textContent = timeOfRun(job.last_run_ts);
      const state = jobPresentation(job);
      row.state.textContent = state.label;
      row.state.dataset.tone = state.tone;
      row.details.el.querySelector("summary")!.setAttribute("aria-label", `Details for ${readableName(job.name)}`);
      row.details.pre.textContent = JSON.stringify(job, null, 2);
    }
    for (const [key, row] of this.jobRows) if (!seen.has(key)) {
      if (row.el.contains(document.activeElement)) this.retry.focus();
      row.el.remove();
      this.jobRows.delete(key);
    }
    this.showJobs.hidden = jobs.length <= 5;
    this.showJobs.textContent = this.allJobs ? "Show fewer jobs" : "Show all jobs";
    this.showJobs.setAttribute("aria-expanded", String(this.allJobs));
  }
}
