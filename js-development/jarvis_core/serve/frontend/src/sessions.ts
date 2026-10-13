/**
 * Sessions presentation — local search and compact previews of hearth records.
 * LAYER: Body. Records stay complete; this module only changes their display.
 */
import { sessions, type Session } from "./api";

export type SourceFilter = "all" | "web" | "terminal";
const PAGE_SIZE = 12;

export function sessionSource(record: Session): Exclude<SourceFilter, "all"> {
  return record.session_id.startsWith("conv-web-") ? "web" : "terminal";
}

export function sessionTitle(record: Session): string {
  const source = record.title?.trim() || record.first_prompt?.trim() || "Untitled conversation";
  const firstLine = source.split(/\r?\n/)[0].replace(/\s+/g, " ");
  const sentence = firstLine.match(/^.*?[!?](?:\s|$)/)?.[0]?.trim() || firstLine;
  const words = sentence.split(" ");
  const short = words.slice(0, 10).join(" ").slice(0, 96).trimEnd();
  return short + (short.length < sentence.length ? "…" : "");
}

export function filterSessions(records: Session[], query: string, source: SourceFilter): Session[] {
  const needle = query.trim().toLocaleLowerCase();
  return records.filter((record) =>
    (source === "all" || sessionSource(record) === source) &&
    (!needle || [record.title, record.first_prompt, record.session_id].some((value) =>
      (value || "").toLocaleLowerCase().includes(needle))),
  );
}

export function sessionPreview(record: Session): string {
  const source = record.first_prompt?.replace(/\s+/g, " ").trim() || "Open to read the full conversation.";
  const preview = source.slice(0, 220).trimEnd();
  return preview + (preview.length < source.length ? "…" : "");
}

export function sessionDate(timestamp?: string, now = new Date()): string {
  const date = new Date(timestamp || "");
  if (!timestamp || !Number.isFinite(date.getTime())) return "Date unavailable";
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const day = date.toDateString() === now.toDateString() ? "Today" :
    date.toDateString() === yesterday.toDateString() ? "Yesterday" :
    date.toLocaleDateString([], { dateStyle: "medium" });
  return `${day} · ${date.toLocaleTimeString([], { timeStyle: "short" })}`;
}

export class SessionsView {
  private records: Session[] = [];
  private loaded = false;
  private loading = false;
  private error = "";
  private limit = PAGE_SIZE;
  private source: SourceFilter = "all";
  private composing = false;
  private search: HTMLInputElement;
  private clear: HTMLButtonElement;
  private grid: HTMLElement;
  private status: HTMLElement;
  private retry: HTMLButtonElement;
  private more: HTMLButtonElement;
  private results: HTMLElement;

  constructor(
    private root: HTMLElement,
    private currentSession: () => string,
    private makeSigil: (id: string) => HTMLCanvasElement,
    private resume: (id: string) => Promise<void>,
  ) {
    const find = <T extends HTMLElement>(selector: string) => root.querySelector<T>(selector)!;
    this.search = find("#session-search");
    this.clear = find("#session-clear");
    this.grid = find("#session-grid");
    this.status = find("#session-status");
    this.retry = find("#session-retry");
    this.more = find("#session-more");
    this.results = find("#session-results");
    const search = () => { this.limit = PAGE_SIZE; this.paint(); };
    this.search.addEventListener("compositionstart", () => { this.composing = true; });
    this.search.addEventListener("compositionend", () => { this.composing = false; search(); });
    this.search.addEventListener("input", () => { if (!this.composing) search(); });
    this.clear.addEventListener("click", () => {
      this.search.value = "";
      search();
      this.search.focus();
    });
    root.querySelectorAll<HTMLButtonElement>("[data-source]").forEach((button) => {
      button.addEventListener("click", () => {
        this.source = button.dataset.source as SourceFilter;
        search();
      });
    });
    this.retry.addEventListener("click", () => void this.refresh());
    this.more.addEventListener("click", () => {
      this.limit += PAGE_SIZE;
      this.paint();
      if (this.more.hidden) this.results.focus();
    });
  }

  async refresh(): Promise<void> {
    if (this.loading) return;
    this.loading = true;
    this.retry.disabled = true;
    this.paint();
    try {
      this.records = await sessions();
      this.loaded = true;
      this.error = "";
    } catch (error) {
      this.error = `Could not refresh conversations. ${(error as Error).message}`;
    } finally {
      this.loading = false;
      this.retry.disabled = false;
      this.paint();
    }
  }

  private paint(): void {
    const filtered = filterSessions(this.records, this.search.value, this.source);
    const visible = filtered.slice(0, this.limit);
    this.clear.hidden = !this.search.value;
    this.root.querySelectorAll<HTMLButtonElement>("[data-source]").forEach((button) =>
      button.setAttribute("aria-pressed", String(button.dataset.source === this.source)));
    this.grid.setAttribute("aria-busy", String(this.loading));
    this.status.textContent = this.error || (!this.loaded ? "Loading conversations…" :
      !this.records.length ? "No conversations yet." :
      !filtered.length ? "No matching conversations. Try another search or source." : "");
    this.status.classList.toggle("bad", !!this.error);
    this.retry.hidden = !this.error;
    this.more.hidden = visible.length >= filtered.length;
    this.results.textContent = this.loaded ? `Showing ${visible.length} of ${filtered.length} conversations` : "";
    this.grid.replaceChildren(...visible.map((record, index) => this.card(record, index)));
  }

  private card(record: Session, index: number): HTMLButtonElement {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "card";
    button.dataset.session = record.session_id;
    button.setAttribute("aria-label", `Open ${sessionTitle(record)}`);
    if (record.session_id === this.currentSession()) button.setAttribute("aria-current", "true");
    button.innerHTML = `<span class="card-kind"></span><p class="card-title"></p>
      <p class="card-preview"></p><span class="card-foot"><span></span><span class="card-arrow" aria-hidden="true">↗</span></span>`;
    button.prepend(this.makeSigil(record.session_id));
    button.querySelector(".card-kind")!.textContent =
      `${String(index + 1).padStart(2, "0")} · ${sessionSource(record) === "web" ? "Web · voice" : "Terminal"}`;
    button.querySelector(".card-title")!.textContent = sessionTitle(record);
    button.querySelector(".card-preview")!.textContent = sessionPreview(record);
    button.querySelector(".card-foot span")!.textContent =
      `${record.turn_count} turns · ${sessionDate(record.latest_ts)}`;
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        await this.resume(record.session_id);
        this.paint();
      } catch (error) {
        this.status.textContent = `Could not open this conversation. ${(error as Error).message}`;
        this.status.classList.add("bad");
      } finally {
        button.disabled = false;
      }
    });
    return button;
  }
}
