import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArrowLeft, Bot, Flag, Pencil, Trash2, X } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { DemoBadge, MethodBadge, SentimentBadge } from "@/components/badges";
import { ConfirmButton, Dialog } from "@/components/dialog";
import { Badge, Button, Card, ErrorState, Field, Input, LoadingBlock, Notice, PageHeader, Select, Textarea } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useWsKey } from "@/lib/hooks";
import { SENTIMENTS, titleCase } from "@/lib/labels";
import type { FeedbackDetail, TopicRow } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

export default function FeedbackDetailPage() {
  const { id = "" } = useParams();
  const ws = useWsKey();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { can } = useAuth();
  const key = [ws, "feedback-detail", id];
  const q = useQuery({ queryKey: key, queryFn: () => api<FeedbackDetail>(`/api/v1/feedback/${id}`) });
  const topics = useQuery({ queryKey: [ws, "topics-list"], queryFn: () => api<TopicRow[]>("/api/v1/topics") });
  const [note, setNote] = useState("");
  const [correctOpen, setCorrectOpen] = useState(false);
  const [label, setLabel] = useState("negative");
  const [reason, setReason] = useState("");
  const [editOpen, setEditOpen] = useState(false);
  const [editText, setEditText] = useState("");
  const [tagText, setTagText] = useState("");
  const [topicId, setTopicId] = useState("");

  const refresh = (d?: unknown) => {
    if (d) qc.setQueryData(key, d);
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: [ws, "feedback"] });
  };
  const mutate = useMutation({
    mutationFn: ({ path, method, body }: { path: string; method: string; body?: unknown }) => api<unknown>(`/api/v1/feedback/${id}${path}`, { method, body }),
    onSuccess: () => refresh(),
    onError: (e) => toast.error((e as Error).message),
  });

  if (q.isLoading) return <LoadingBlock rows={8} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => q.refetch()} />;
  const f = q.data!;
  const canWrite = can("feedback:write");

  return (
    <div>
      <Link to="/feedback" className="mb-3 inline-flex items-center gap-1 text-sm text-muted hover:text-ink">
        <ArrowLeft className="h-4 w-4" /> Back to feedback
      </Link>
      <PageHeader
        title={f.title || "Feedback record"}
        description={`Received ${formatDateTime(f.received_at)}${f.source ? ` via ${f.source.name}` : ""}`}
        actions={
          canWrite && (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setEditText(f.text);
                  setEditOpen(true);
                }}
              >
                <Pencil className="h-3.5 w-3.5" /> Edit
              </Button>
              <Button size="sm" variant="outline" onClick={() => mutate.mutate({ path: "", method: "PATCH", body: { needs_review: !f.needs_review } })}>
                <Flag className="h-3.5 w-3.5" /> {f.needs_review ? "Clear review flag" : "Mark for review"}
              </Button>
              <Button size="sm" variant="outline" onClick={() => mutate.mutate({ path: "", method: "PATCH", body: { is_archived: !f.is_archived } })}>
                <Archive className="h-3.5 w-3.5" /> {f.is_archived ? "Unarchive" : "Archive"}
              </Button>
              {can("analysis:run") && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={async () => {
                    try {
                      await api("/api/v1/analysis/run", { method: "POST", body: { feedback_ids: [f.id] } });
                      toast.success("AI analysis queued. Refresh in a moment to see the result.");
                    } catch (e) {
                      toast.error((e as Error).message);
                    }
                  }}
                >
                  <Bot className="h-3.5 w-3.5" /> Analyse with AI
                </Button>
              )}
              {can("feedback:delete") && (
                <ConfirmButton
                  title="Delete this feedback record?"
                  description="The record, its analyses and notes are permanently deleted. Archiving keeps it out of analytics without deleting it."
                  onConfirm={async () => {
                    await api(`/api/v1/feedback/${f.id}`, { method: "DELETE" });
                    toast.success("Feedback deleted");
                    qc.invalidateQueries({ queryKey: [ws] });
                    navigate("/feedback");
                  }}
                  trigger={(open) => (
                    <Button size="sm" variant="danger" onClick={open}>
                      <Trash2 className="h-3.5 w-3.5" /> Delete
                    </Button>
                  )}
                />
              )}
            </>
          )
        }
      />
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card title="Original feedback">
            <p className="prose-plain">{f.text}</p>
            <div className="mt-4 flex flex-wrap gap-1.5">
              {f.is_demo && <DemoBadge />}
              {f.needs_review && <Badge tone="amber">Needs review</Badge>}
              {f.is_archived && <Badge tone="slate">Archived</Badge>}
              {f.language && <Badge tone="slate">Language: {f.language}</Badge>}
            </div>
          </Card>
          <Card
            title="Sentiment"
            actions={
              can("feedback:correct") && (
                <Button size="sm" variant="outline" onClick={() => setCorrectOpen(true)}>
                  Correct classification
                </Button>
              )
            }
          >
            <div className="flex flex-wrap items-center gap-2">
              <SentimentBadge label={f.sentiment.label} />
              <MethodBadge method={f.sentiment.method} />
              {f.sentiment.score !== null && <span className="text-sm text-muted">Score {f.sentiment.score > 0 ? "+" : ""}{f.sentiment.score.toFixed(2)}</span>}
              {f.sentiment.confidence !== null && (
                <span className="text-sm text-muted" title="Model-reported confidence. It is not a guarantee of correctness.">
                  Model confidence {(f.sentiment.confidence * 100).toFixed(0)}%
                </span>
              )}
              {f.primary_emotion && <Badge tone="violet">Emotion cue: {titleCase(f.primary_emotion)}</Badge>}
            </div>
            <h3 className="mb-2 mt-5 text-xs font-semibold uppercase tracking-wide text-muted">Classification history (newest first)</h3>
            <ol className="space-y-3">
              {f.analyses.map((a) => (
                <li key={a.id} className="rounded-lg border border-line p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <SentimentBadge label={a.label} />
                    <MethodBadge method={a.method} />
                    {a.model && <span className="text-xs text-muted">{a.model}</span>}
                    <span className="ml-auto text-xs text-muted">{formatDateTime(a.created_at)}</span>
                  </div>
                  <p className="mt-2 text-muted">{a.explanation}</p>
                  {a.method === "manual" && (
                    <p className="mt-1 text-xs text-muted">
                      Changed from {a.previous_label ?? "unclassified"} by {a.corrected_by ?? "a user"}
                    </p>
                  )}
                  {a.evidence.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {a.evidence.map((e, i) => (
                        <span key={i} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">
                          “{e}”
                        </span>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ol>
          </Card>
          <Card title="Internal notes">
            <ul className="mb-3 space-y-2">
              {f.notes.length === 0 && <li className="text-sm text-muted">No notes yet.</li>}
              {f.notes.map((n) => (
                <li key={n.id} className="flex items-start justify-between gap-2 rounded-lg bg-slate-50 p-3 text-sm">
                  <div>
                    <p className="prose-plain">{n.body}</p>
                    <p className="mt-1 text-xs text-muted">
                      {n.author ?? "Unknown"} · {formatDateTime(n.created_at)}
                    </p>
                  </div>
                  {canWrite && (
                    <button aria-label="Delete note" className="text-muted hover:text-red-600" onClick={() => mutate.mutate({ path: `/notes/${n.id}`, method: "DELETE" })}>
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
            {canWrite && (
              <form
                className="flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!note.trim()) return;
                  mutate.mutate({ path: "/notes", method: "POST", body: { body: note } }, { onSuccess: () => setNote("") });
                }}
              >
                <Input aria-label="New note" placeholder="Add an internal note…" value={note} onChange={(e) => setNote(e.target.value)} />
                <Button type="submit" size="sm">
                  Add
                </Button>
              </form>
            )}
          </Card>
        </div>
        <div className="space-y-5">
          <Card title="Details">
            <dl className="space-y-2 text-sm">
              {[
                ["Product", f.product?.name],
                ["Source", f.source?.name],
                ["Rating", f.rating !== null ? `${f.rating} / ${f.rating_max ?? 5}` : null],
                ["Customer reference", f.customer_ref],
                ["Segment", f.customer_segment],
                ["External ID", f.external_id],
                ["AI analysis", titleCase(f.ai_status)],
                ["Record ID", f.id],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3">
                  <dt className="text-muted">{k}</dt>
                  <dd className="break-all text-right">{v || "—"}</dd>
                </div>
              ))}
            </dl>
          </Card>
          <Card title="Topics">
            <ul className="space-y-2">
              {f.topics.length === 0 && <li className="text-sm text-muted">No topics assigned.</li>}
              {f.topics.map((t) => (
                <li key={t.id} className="text-sm">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium">{t.name}</span>
                    <span className="flex items-center gap-1.5">
                      {t.sentiment && <SentimentBadge label={t.sentiment} />}
                      <Badge tone="slate">{t.assigned_by === "rule" ? "keyword rule" : t.assigned_by}</Badge>
                      {canWrite && (
                        <button aria-label={`Remove topic ${t.name}`} className="text-muted hover:text-red-600" onClick={() => mutate.mutate({ path: `/topics/${t.id}`, method: "DELETE" })}>
                          <X className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </span>
                  </div>
                  {t.evidence && <p className="mt-0.5 text-xs text-muted">“{t.evidence}”</p>}
                </li>
              ))}
            </ul>
            {canWrite && (
              <div className="mt-3 flex gap-2">
                <Select aria-label="Assign topic" value={topicId} onChange={(e) => setTopicId(e.target.value)}>
                  <option value="">Assign a topic…</option>
                  {(topics.data ?? []).map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
                </Select>
                <Button size="sm" variant="outline" disabled={!topicId} onClick={() => mutate.mutate({ path: "/topics", method: "POST", body: { topic_id: topicId } }, { onSuccess: () => setTopicId("") })}>
                  Add
                </Button>
              </div>
            )}
          </Card>
          <Card title="Tags">
            <div className="flex flex-wrap gap-1.5">
              {f.tags.length === 0 && <span className="text-sm text-muted">No tags.</span>}
              {f.tags.map((t) => (
                <Badge key={t.id} tone="slate">
                  #{t.name}
                  {canWrite && (
                    <button aria-label={`Remove tag ${t.name}`} onClick={() => mutate.mutate({ path: "/tags", method: "PUT", body: { tags: f.tags.filter((x) => x.id !== t.id).map((x) => x.name) } })}>
                      <X className="h-3 w-3" />
                    </button>
                  )}
                </Badge>
              ))}
            </div>
            {canWrite && (
              <form
                className="mt-3 flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  if (!tagText.trim()) return;
                  mutate.mutate({ path: "/tags", method: "PUT", body: { tags: [...f.tags.map((x) => x.name), tagText.trim()] } }, { onSuccess: () => setTagText("") });
                }}
              >
                <Input aria-label="New tag" placeholder="Add tag" value={tagText} onChange={(e) => setTagText(e.target.value)} />
                <Button size="sm" variant="outline" type="submit">
                  Add
                </Button>
              </form>
            )}
          </Card>
          {f.emotions[0] && (
            <Card title="Emotion cues" description="Indicates wording only - not a psychological assessment">
              <ul className="space-y-1 text-sm">
                {f.emotions[0].emotions.length === 0 && <li className="text-muted">None detected.</li>}
                {f.emotions[0].emotions.map((e) => (
                  <li key={e.emotion} className="flex justify-between">
                    <span>{titleCase(e.emotion)}</span>
                    <span className="text-muted">{e.confidence !== null ? `${Math.round(e.confidence * 100)}%` : "keyword cue"}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-muted">Method: {f.emotions[0].method === "ai" ? `AI (${f.emotions[0].model})` : "keyword cues (not AI)"}</p>
            </Card>
          )}
        </div>
      </div>

      <Dialog
        open={correctOpen}
        onOpenChange={setCorrectOpen}
        title="Correct sentiment"
        description="The previous classification is kept in the history; your correction is recorded with your name."
        footer={
          <>
            <Button variant="outline" onClick={() => setCorrectOpen(false)}>
              Cancel
            </Button>
            <Button
              loading={mutate.isPending}
              onClick={() =>
                mutate.mutate(
                  { path: "/sentiment", method: "POST", body: { label, note: reason } },
                  {
                    onSuccess: () => {
                      toast.success("Classification corrected");
                      setCorrectOpen(false);
                    },
                  },
                )
              }
            >
              Save correction
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Correct sentiment" htmlFor="label">
            <Select id="label" value={label} onChange={(e) => setLabel(e.target.value)}>
              {SENTIMENTS.map((s) => (
                <option key={s} value={s}>
                  {titleCase(s)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Reason (optional)" htmlFor="reason">
            <Input id="reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. sarcasm" />
          </Field>
        </div>
      </Dialog>
      <Dialog
        open={editOpen}
        onOpenChange={setEditOpen}
        title="Edit feedback text"
        wide
        footer={
          <>
            <Button variant="outline" onClick={() => setEditOpen(false)}>
              Cancel
            </Button>
            <Button
              loading={mutate.isPending}
              disabled={!editText.trim()}
              onClick={() =>
                mutate.mutate(
                  { path: "", method: "PATCH", body: { text: editText } },
                  {
                    onSuccess: () => {
                      toast.success("Saved. The record was re-analysed; earlier analyses stay in the history.");
                      setEditOpen(false);
                    },
                  },
                )
              }
            >
              Save
            </Button>
          </>
        }
      >
        <Notice tone="amber" className="mb-3">
          Edit only to fix transcription errors. Changing the text re-runs the rule-based analysis; previous AI and manual results remain in the history.
        </Notice>
        <Textarea aria-label="Feedback text" rows={8} value={editText} onChange={(e) => setEditText(e.target.value)} />
      </Dialog>
    </div>
  );
}
