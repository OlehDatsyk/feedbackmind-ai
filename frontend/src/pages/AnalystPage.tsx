import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Calculator, MessageSquarePlus, Send, Trash2, User } from "lucide-react";
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { AIGeneratedBadge } from "@/components/badges";
import { Badge, Button, Card, Notice, PageHeader, Spinner, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { useWsKey } from "@/lib/hooks";
import type { AIInfo, ChatMessage } from "@/lib/types";
import { cn, timeAgo } from "@/lib/utils";

const SUGGESTIONS = [
  "What are customers complaining about most?",
  "Which product has the highest negative sentiment?",
  "What changed this month?",
  "What do customers like about our service?",
  "Which topics are becoming more negative?",
  "Summarise feedback from the last 30 days",
  "What should we improve first?",
];

/** Minimal, safe Markdown: paragraphs, bullets, **bold**, _italic_ and [#record-id] citations. No raw HTML. */
function Inline({ text }: { text: string }) {
  const parts: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|_[^_]+_|\[#([0-9a-f-]{36})\])/gi;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) parts.push(<strong key={k++}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("_")) parts.push(<em key={k++}>{tok.slice(1, -1)}</em>);
    else
      parts.push(
        <Link key={k++} to={`/feedback/${m[2]}`} className="rounded bg-accent-50 px-1 font-mono text-[11px] text-accent-700 hover:underline" title="Open cited feedback record">
          #{m[2].slice(0, 8)}
        </Link>,
      );
    last = m.index + tok.length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return <>{parts}</>;
}

function Markdown({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <div className="space-y-2 text-sm leading-relaxed">
      {blocks.map((b, i) => {
        const lines = b.split("\n");
        if (lines.every((l) => /^\s*([-*]|\d+\.)\s+/.test(l) || l.startsWith("> "))) {
          if (lines[0].startsWith("> ")) return <blockquote key={i} className="border-l-2 border-line pl-3 text-muted"><Inline text={lines.map((l) => l.slice(2)).join(" ")} /></blockquote>;
          return (
            <ul key={i} className="list-disc space-y-1 pl-5">
              {lines.map((l, j) => (
                <li key={j}>
                  <Inline text={l.replace(/^\s*([-*]|\d+\.)\s+/, "")} />
                </li>
              ))}
            </ul>
          );
        }
        return (
          <p key={i}>
            {lines.map((l, j) => (
              <Fragment key={j}>
                {j > 0 && <br />}
                <Inline text={l.replace(/^#+\s*/, "")} />
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}

function MessageView({ m }: { m: ChatMessage }) {
  const user = m.role === "user";
  const period = m.facts?.period;
  return (
    <div className={cn("flex gap-3", user && "flex-row-reverse")}>
      <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-full", user ? "bg-navy-900 text-white" : "bg-accent-50 text-accent-700")}>{user ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}</div>
      <div className={cn("max-w-[85%] rounded-xl px-4 py-3", user ? "bg-navy-900 text-white" : "border border-line bg-white")}>
        {user ? (
          <p className="whitespace-pre-wrap text-sm">{m.content}</p>
        ) : (
          <>
            <div className="mb-2 flex flex-wrap gap-1.5">
              {m.ai_generated ? <AIGeneratedBadge model={m.model} /> : <Badge tone="slate"><Calculator className="h-3 w-3" /> Computed figures only</Badge>}
              {period && <Badge tone="blue">Date range: {period.label}{period.from ? ` (${period.from} – ${period.to})` : ""}</Badge>}
              {m.facts?.sample_size !== undefined && <Badge tone="slate">Sample: {m.facts.sample_size} records</Badge>}
              {m.facts?.data_sufficient === false && <Badge tone="amber">Insufficient data</Badge>}
            </div>
            <Markdown text={m.content} />
            {m.citations.length > 0 && (
              <p className="mt-3 flex flex-wrap gap-x-1.5 text-xs text-muted">
                Cited records:{" "}
                {m.citations.map((c) => (
                  <Link key={c} to={`/feedback/${c}`} className="mr-1.5 font-mono text-accent-700 hover:underline">
                    #{c.slice(0, 8)}
                  </Link>
                ))}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function AnalystPage() {
  const ws = useWsKey();
  const qc = useQueryClient();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [pendingQ, setPendingQ] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const convs = useQuery({ queryKey: [ws, "conversations"], queryFn: () => api<{ id: string; title: string; updated_at: string }[]>("/api/v1/assistant/conversations") });
  const conv = useQuery({
    queryKey: [ws, "conversation", conversationId],
    queryFn: () => api<{ id: string; messages: ChatMessage[] }>(`/api/v1/assistant/conversations/${conversationId}`),
    enabled: !!conversationId,
  });
  const ai = useQuery({ queryKey: [ws, "ai-status"], queryFn: () => api<{ ai: AIInfo }>("/api/v1/analysis/status") });
  const ask = useMutation({
    mutationFn: (q: string) => api<{ conversation_id: string }>("/api/v1/assistant/ask", { method: "POST", body: { question: q, conversation_id: conversationId } }),
    onMutate: (q) => setPendingQ(q),
    onSuccess: (r) => {
      setConversationId(r.conversation_id);
      qc.invalidateQueries({ queryKey: [ws, "conversation", r.conversation_id] });
      qc.invalidateQueries({ queryKey: [ws, "conversations"] });
      setQuestion("");
    },
    onError: (e) => toast.error((e as Error).message),
    onSettled: () => setPendingQ(null),
  });
  const del = useMutation({
    mutationFn: (id: string) => api(`/api/v1/assistant/conversations/${id}`, { method: "DELETE" }),
    onSuccess: (_, id) => {
      if (id === conversationId) setConversationId(null);
      qc.invalidateQueries({ queryKey: [ws, "conversations"] });
    },
  });
  const messages = conversationId ? conv.data?.messages ?? [] : [];
  useEffect(() => {
    // Braces matter: newer browsers return a Promise from scrollIntoView, which must not be returned from an effect.
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, pendingQ]);
  const submit = (q: string) => {
    if (q.trim().length < 2 || ask.isPending) return;
    ask.mutate(q.trim());
  };

  return (
    <div>
      <PageHeader title="AI Business Analyst" description="Ask questions about this workspace's feedback. Numbers are computed from the database; AI (when configured) explains them and cites records." />
      {ai.data && !ai.data.ai.configured && (
        <Notice tone="blue" className="mb-4">
          AI is not configured, so answers contain computed figures and relevant records only - no AI interpretation. Configure a provider in Settings → AI provider for written analysis.
        </Notice>
      )}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[16rem_1fr]">
        <Card title="Conversations" className="h-fit" actions={<Button size="sm" variant="ghost" onClick={() => setConversationId(null)} aria-label="New conversation"><MessageSquarePlus className="h-4 w-4" /></Button>}>
          <ul className="-mx-2 space-y-0.5">
            {convs.data?.length === 0 && <li className="px-2 text-sm text-muted">No conversations yet.</li>}
            {convs.data?.map((c) => (
              <li key={c.id} className="group flex items-center gap-1">
                <button onClick={() => setConversationId(c.id)} className={cn("min-w-0 flex-1 rounded-md px-2 py-1.5 text-left text-sm hover:bg-slate-100", c.id === conversationId && "bg-slate-100 font-medium")}>
                  <span className="block truncate">{c.title}</span>
                  <span className="text-xs text-muted">{timeAgo(c.updated_at)}</span>
                </button>
                <button aria-label="Delete conversation" onClick={() => del.mutate(c.id)} className="rounded p-1 text-muted opacity-0 hover:text-red-600 group-hover:opacity-100 focus:opacity-100">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        </Card>
        <div className="card flex min-h-[32rem] flex-col">
          <div className="flex-1 space-y-4 overflow-y-auto p-5" aria-live="polite">
            {messages.length === 0 && !pendingQ && (
              <div className="py-6 text-center">
                <Bot className="mx-auto h-8 w-8 text-accent-600" />
                <h2 className="mt-2 text-sm font-semibold">Ask about your customer feedback</h2>
                <p className="mx-auto mt-1 max-w-md text-sm text-muted">Mention a period ("last 30 days", "this month") or a product name to narrow the scope.</p>
                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} onClick={() => submit(s)} className="rounded-full border border-line px-3 py-1.5 text-xs hover:border-accent-600 hover:text-accent-700">
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m) => (
              <MessageView key={m.id} m={m} />
            ))}
            {pendingQ && (
              <>
                <MessageView m={{ id: "pending", role: "user", content: pendingQ, citations: [], facts: {}, ai_generated: false, provider: null, model: null, created_at: "" }} />
                <div className="flex items-center gap-2 pl-11 text-sm text-muted">
                  <Spinner /> Querying your data…
                </div>
              </>
            )}
            <div ref={endRef} />
          </div>
          <form
            className="flex gap-2 border-t border-line p-3"
            onSubmit={(e) => {
              e.preventDefault();
              submit(question);
            }}
          >
            <Textarea
              aria-label="Your question"
              rows={1}
              className="min-h-[42px]"
              placeholder="e.g. Compare Aurora Desk Lamp and Nimbus Mobile App"
              value={question}
              maxLength={2000}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit(question);
                }
              }}
            />
            <Button type="submit" loading={ask.isPending} disabled={question.trim().length < 2} aria-label="Send">
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
