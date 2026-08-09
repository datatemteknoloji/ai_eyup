import { Bot, Eraser, Loader2, Send, ThumbsDown, X } from "lucide-react";
import { FormEvent, PointerEvent as ReactPointerEvent, useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  assistantCapabilities,
  assistantChat,
  assistantFeedback,
  assistantHistory,
  assistantHistoryClear,
  AssistantChatResult,
} from "@dropt/api";
import { Button } from "@dropt/components/ui/button";
import { useT } from "@dropt/i18n/I18nProvider";
import type { TranslationKey } from "@dropt/i18n/messages";
import { getToken } from "@dropt/session";
import { toLevel1OpsPath } from "@dropt/components/ServerOpsMenu";

type CapOpt = { id: string; title_tr: string; route: string };

function mapAssistantRoute(path: string): string {
  if (!path) return path;
  if (path.startsWith("/level1/")) return path;
  if (path.startsWith("/app/servers")) return "/level1";
  if (path.startsWith("/app/jobs")) return path.replace(/^\/app\/jobs/, "/level1/jobs");
  if (path.startsWith("/app/")) return toLevel1OpsPath(path);
  return path;
}

type ChatItem =
  | { role: "user"; text: string }
  | {
      role: "assistant";
      text: string;
      result?: AssistantChatResult;
      userMessage?: string;
      feedbackDone?: boolean;
    };

type FabPos = { x: number; y: number };

const FAB_SIZE = 48;
const FAB_MARGIN = 12;
const POS_KEY = "dropt.assistant.fab.pos";
const DRAG_THRESHOLD = 6;

function clampPos(pos: FabPos): FabPos {
  const maxX = Math.max(FAB_MARGIN, window.innerWidth - FAB_SIZE - FAB_MARGIN);
  const maxY = Math.max(FAB_MARGIN, window.innerHeight - FAB_SIZE - FAB_MARGIN);
  return {
    x: Math.min(maxX, Math.max(FAB_MARGIN, pos.x)),
    y: Math.min(maxY, Math.max(FAB_MARGIN, pos.y)),
  };
}

function defaultPos(): FabPos {
  return clampPos({
    x: window.innerWidth - FAB_SIZE - 20,
    y: window.innerHeight - FAB_SIZE - 20,
  });
}

function loadPos(): FabPos {
  try {
    const raw = localStorage.getItem(POS_KEY);
    if (!raw) return defaultPos();
    const parsed = JSON.parse(raw) as Partial<FabPos>;
    if (typeof parsed.x === "number" && typeof parsed.y === "number") {
      return clampPos({ x: parsed.x, y: parsed.y });
    }
  } catch {
    /* ignore */
  }
  return defaultPos();
}

function savePos(pos: FabPos) {
  try {
    localStorage.setItem(POS_KEY, JSON.stringify(pos));
  } catch {
    /* ignore */
  }
}

function formatResultText(result: AssistantChatResult, t: (k: TranslationKey) => string): string {
  const lines = [result.summary_tr];
  const opTitle = result.title_tr?.trim() || null;
  if (opTitle) lines.push(`${t("assistant_suggested")}: ${opTitle}`);
  if (result.server_hostnames?.length) {
    lines.push(`${t("assistant_target")}: ${result.server_hostnames.join(", ")}`);
  }
  if (result.reference_hostnames?.length) {
    lines.push(`${t("assistant_reference")}: ${result.reference_hostnames.join(", ")}`);
  }
  if (result.checklist_tr?.length) {
    lines.push(`${t("assistant_checklist")}:`);
    result.checklist_tr.forEach((c, i) => lines.push(`${i + 1}. ${c}`));
  }
  if (result.analysis_tr?.trim()) {
    lines.push(result.analysis_tr.trim());
  }
  if (result.clarifying_questions?.length) {
    lines.push(`${t("assistant_clarify")}:`);
    result.clarifying_questions.forEach((q) => lines.push(`• ${q}`));
  }
  if (result.out_of_scope_note) lines.push(`${t("assistant_note")}: ${result.out_of_scope_note}`);
  return lines.filter(Boolean).join("\n");
}

export function AssistantFab() {
  const navigate = useNavigate();
  const t = useT();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [caps, setCaps] = useState<CapOpt[]>([]);
  const [feedbackIdx, setFeedbackIdx] = useState<number | null>(null);
  const [items, setItems] = useState<ChatItem[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [pos, setPos] = useState<FabPos>(() =>
    typeof window !== "undefined" ? loadPos() : { x: 20, y: 20 },
  );
  const [dragging, setDragging] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const lastUserMsg = useRef("");
  const skipClickRef = useRef(false);
  const dragRef = useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    originX: number;
    originY: number;
    moved: boolean;
  } | null>(null);

  const reclamp = useCallback(() => {
    setPos((p) => {
      const next = clampPos(p);
      if (next.x !== p.x || next.y !== p.y) savePos(next);
      return next;
    });
  }, []);

  useEffect(() => {
    window.addEventListener("resize", reclamp);
    return () => window.removeEventListener("resize", reclamp);
  }, [reclamp]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items, open, feedbackIdx]);

  useEffect(() => {
    if (!open || historyLoaded) return;
    const token = getToken();
    if (!token) return;
    void (async () => {
      try {
        const hist = await assistantHistory(token);
        if (hist.length) {
          const mapped: ChatItem[] = hist.map((h) => {
            if (h.role === "user") return { role: "user", text: h.content };
            return {
              role: "assistant",
              text: h.content,
              result: h.result || undefined,
            };
          });
          setItems(mapped);
        } else {
          setItems([{ role: "assistant", text: t("assistant_hello") }]);
        }
      } catch {
        setItems([{ role: "assistant", text: t("assistant_hello") }]);
      } finally {
        setHistoryLoaded(true);
      }
    })();
  }, [open, historyLoaded, t]);

  useEffect(() => {
    if (!open || caps.length) return;
    const token = getToken();
    if (!token) return;
    void assistantCapabilities(token)
      .then(setCaps)
      .catch(() => undefined);
  }, [open, caps.length]);

  async function onClear() {
    const token = getToken();
    if (!token || busy) return;
    try {
      await assistantHistoryClear(token);
      setItems([{ role: "assistant", text: t("assistant_hello") }]);
      setFeedbackIdx(null);
    } catch {
      /* ignore */
    }
  }

  async function onSend(e?: FormEvent) {
    e?.preventDefault();
    const token = getToken();
    const msg = input.trim();
    if (!token || !msg || busy) return;
    setInput("");
    lastUserMsg.current = msg;
    setItems((prev) => [...prev, { role: "user", text: msg }]);
    setBusy(true);
    setFeedbackIdx(null);
    try {
      const result = await assistantChat(token, msg);
      setItems((prev) => [
        ...prev,
        {
          role: "assistant",
          text: formatResultText(result, t),
          result,
          userMessage: msg,
        },
      ]);
    } catch (err) {
      setItems((prev) => [
        ...prev,
        {
          role: "assistant",
          text: err instanceof Error ? err.message : t("assistant_error"),
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function submitFeedback(itemIdx: number, correctId: string) {
    const token = getToken();
    const item = items[itemIdx];
    if (!token || !item || item.role !== "assistant" || !item.result) return;
    try {
      await assistantFeedback(token, {
        message: item.userMessage || lastUserMsg.current,
        suggested_operation_id: item.result.operation_id || "",
        correct_operation_id: correctId,
      });
      setItems((prev) =>
        prev.map((it, i) => (i === itemIdx && it.role === "assistant" ? { ...it, feedbackDone: true } : it)),
      );
      setFeedbackIdx(null);
    } catch {
      /* ignore */
    }
  }

  function onFabPointerDown(e: ReactPointerEvent<HTMLButtonElement>) {
    if (e.button !== 0) return;
    dragRef.current = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      originX: pos.x,
      originY: pos.y,
      moved: false,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(true);
  }

  function onFabPointerMove(e: ReactPointerEvent<HTMLButtonElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    const dx = e.clientX - drag.startX;
    const dy = e.clientY - drag.startY;
    if (!drag.moved && Math.hypot(dx, dy) >= DRAG_THRESHOLD) {
      drag.moved = true;
    }
    if (!drag.moved) return;
    setPos(clampPos({ x: drag.originX + dx, y: drag.originY + dy }));
  }

  function onFabPointerUp(e: ReactPointerEvent<HTMLButtonElement>) {
    const drag = dragRef.current;
    if (!drag || drag.pointerId !== e.pointerId) return;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
    skipClickRef.current = drag.moved;
    if (drag.moved) {
      setPos((p) => {
        const next = clampPos(p);
        savePos(next);
        return next;
      });
    }
    dragRef.current = null;
    setDragging(false);
  }

  const panelH = Math.min(typeof window !== "undefined" ? window.innerHeight * 0.7 : 520, 520);
  const spaceAbove = pos.y - FAB_MARGIN;
  const spaceBelow = (typeof window !== "undefined" ? window.innerHeight : 800) - pos.y - FAB_SIZE - FAB_MARGIN;
  const openAbove = spaceAbove >= Math.min(panelH, 280) || spaceAbove >= spaceBelow;
  const alignRight = pos.x + FAB_SIZE / 2 > (typeof window !== "undefined" ? window.innerWidth : 800) / 2;

  return (
    <div className="pointer-events-none fixed inset-0 z-50">
      <div
        className="pointer-events-none absolute"
        style={{ left: pos.x, top: pos.y, width: FAB_SIZE, height: FAB_SIZE }}
      >
        {open ? (
          <div
            className="pointer-events-auto absolute flex h-[min(70vh,520px)] w-[min(92vw,380px)] flex-col overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-card)] shadow-2xl"
            style={{
              ...(openAbove ? { bottom: FAB_SIZE + 12 } : { top: FAB_SIZE + 12 }),
              ...(alignRight ? { right: 0 } : { left: 0 }),
            }}
          >
            <div className="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Bot className="h-4 w-4 text-[var(--color-primary)]" />
                {t("assistant_title")}
              </div>
              <div className="flex items-center gap-0.5">
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7"
                  title={t("assistant_clear_title")}
                  aria-label={t("assistant_clear")}
                  onClick={() => void onClear()}
                >
                  <Eraser className="h-3.5 w-3.5" />
                </Button>
                <Button type="button" size="icon" variant="ghost" className="h-7 w-7" onClick={() => setOpen(false)}>
                  <X className="h-4 w-4" />
                </Button>
              </div>
            </div>
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3 text-sm">
              {items.map((it, idx) => (
                <div
                  key={idx}
                  className={
                    it.role === "user"
                      ? "ml-8 rounded-xl bg-[var(--color-primary)]/15 px-3 py-2 whitespace-pre-wrap"
                      : "mr-4 rounded-xl border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2 whitespace-pre-wrap"
                  }
                >
                  {it.text}
                  {it.role === "assistant" && it.result?.route ? (
                    <div className="mt-2 space-y-2">
                      <Button
                        type="button"
                        size="sm"
                        className="h-7"
                        onClick={() => {
                          navigate(mapAssistantRoute(it.result!.deep_link || it.result!.route!));
                          setOpen(false);
                        }}
                      >
                        {it.result.title_tr || t("assistant_open")} →
                      </Button>
                      <p className="text-[10px] text-[var(--color-muted-foreground)]">
                        {t("assistant_confidence")} {Math.round((it.result.confidence || 0) * 100)}% · {it.result.source}
                        {it.result.server_ids?.length ? ` · id ${it.result.server_ids.join(",")}` : ""}
                      </p>
                      {!it.feedbackDone ? (
                        <div className="flex flex-wrap items-center gap-1">
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            className="h-6 gap-1 px-1.5 text-[10px] text-[var(--color-muted-foreground)]"
                            onClick={() => setFeedbackIdx(feedbackIdx === idx ? null : idx)}
                            title={t("assistant_wrong_hint")}
                          >
                            <ThumbsDown className="h-3 w-3" />
                            {t("assistant_wrong_ops")}
                          </Button>
                        </div>
                      ) : (
                        <p className="text-[10px] text-emerald-600">{t("assistant_thanks")}</p>
                      )}
                      {feedbackIdx === idx && !it.feedbackDone ? (
                        <div className="max-h-28 space-y-0.5 overflow-y-auto rounded border border-[var(--color-border)] p-1">
                          <p className="px-1 text-[10px] text-[var(--color-muted-foreground)]">
                            {t("assistant_pick_correct")}
                          </p>
                          {caps.map((c) => (
                            <button
                              key={c.id}
                              type="button"
                              className="block w-full rounded px-1.5 py-1 text-left text-[11px] hover:bg-[var(--color-accent)]"
                              onClick={() => void submitFeedback(idx, c.id)}
                            >
                              {c.title_tr}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
            <form onSubmit={onSend} className="flex gap-2 border-t border-[var(--color-border)] p-2">
              <textarea
                className="min-h-[44px] max-h-28 flex-1 resize-none rounded-md border border-[var(--color-border)] bg-[var(--color-background)] px-2 py-1.5 text-xs outline-none focus:ring-1 focus:ring-[var(--color-primary)]"
                placeholder={t("assistant_placeholder")}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void onSend();
                  }
                }}
              />
              <Button type="submit" size="icon" className="h-10 w-10 shrink-0" disabled={busy || !input.trim()}>
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              </Button>
            </form>
          </div>
        ) : null}

        <button
          type="button"
          className={`pointer-events-auto flex h-12 w-12 touch-none items-center justify-center rounded-full bg-[var(--color-primary)] text-[var(--color-primary-foreground)] shadow-lg ring-2 ring-[var(--color-primary)]/30 transition hover:scale-105 ${
            dragging ? "cursor-grabbing scale-105" : "cursor-grab"
          }`}
          title={`${t("assistant_title")} — ${t("assistant_drag_hint")}`}
          aria-label={t("assistant_title")}
          onPointerDown={onFabPointerDown}
          onPointerMove={onFabPointerMove}
          onPointerUp={onFabPointerUp}
          onPointerCancel={onFabPointerUp}
          onClick={() => {
            if (skipClickRef.current) {
              skipClickRef.current = false;
              return;
            }
            setOpen((v) => !v);
          }}
        >
          {open ? <X className="h-5 w-5" /> : <Bot className="h-5 w-5" />}
        </button>
      </div>
    </div>
  );
}
