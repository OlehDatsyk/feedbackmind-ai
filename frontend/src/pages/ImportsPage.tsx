import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileSpreadsheet, Loader2, UploadCloud, XCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Badge, Button, Card, EmptyState, ErrorState, Field, LoadingBlock, Notice, PageHeader, Progress, Select } from "@/components/ui";
import { api, downloadFile } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useJob, useWsKey } from "@/lib/hooks";
import { IMPORT_STATUS } from "@/lib/labels";
import type { ImportJob } from "@/lib/types";
import { cn, formatBytes, formatDateTime } from "@/lib/utils";

interface FieldsInfo {
  fields: { key: string; label: string; required: boolean }[];
  max_file_mb: number;
  max_rows: number;
  accepted_types: string[];
  encodings: string[];
}

interface Validation {
  import: ImportJob;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  duplicate_rows: number;
  date_defaulted_rows: number;
  duplicates_will_be: string;
  preview: Record<string, unknown>[];
  errors: { row_number: number; error_type: string; message: string; raw: Record<string, string> }[];
}

const STEPS = ["Upload", "Columns", "Map fields", "Preview", "Validate", "Confirm", "Process"];

function Stepper({ step }: { step: number }) {
  return (
    <ol className="mb-5 flex flex-wrap gap-2" aria-label="Import steps">
      {STEPS.map((s, i) => (
        <li
          key={s}
          aria-current={i === step ? "step" : undefined}
          className={cn("flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium", i < step ? "border-accent-100 bg-accent-50 text-accent-700" : i === step ? "border-navy-900 bg-navy-900 text-white" : "border-line text-muted")}
        >
          <span>{i + 1}</span> {s}
        </li>
      ))}
    </ol>
  );
}

function Wizard({ fields, initial, onDone }: { fields: FieldsInfo; initial: ImportJob | null; onDone: () => void }) {
  const qc = useQueryClient();
  const ws = useWsKey();
  const fileRef = useRef<HTMLInputElement>(null);
  const [encoding, setEncoding] = useState("");
  const [imp, setImp] = useState<ImportJob | null>(initial);
  const [mapping, setMapping] = useState<Record<string, string>>(initial?.mapping ?? {});
  const [opts, setOpts] = useState({ date_order: "auto", missing_date: "reject", rating_scale: "5", default_source: "", default_product: "", skip_duplicates: true });
  const [validation, setValidation] = useState<Validation | null>(null);
  const [jobId, setJobId] = useState<string | null>(initial?.job_id ?? null);
  const job = useJob(jobId);
  const [dragOver, setDragOver] = useState(false);

  const step = !imp ? 0 : jobId ? 6 : validation ? 4 : 2;

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      if (encoding) form.append("encoding", encoding);
      return api<ImportJob>("/api/v1/imports", { method: "POST", form });
    },
    onSuccess: (r) => {
      setImp(r);
      setMapping(r.mapping);
      setValidation(null);
      qc.invalidateQueries({ queryKey: [ws, "imports"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const validate = useMutation({
    mutationFn: () =>
      api<Validation>(`/api/v1/imports/${imp!.id}/validate`, {
        method: "POST",
        body: { mapping, options: { ...opts, rating_scale: Number(opts.rating_scale), default_source: opts.default_source || null, default_product: opts.default_product || null } },
      }),
    onSuccess: (r) => setValidation(r),
    onError: (e) => toast.error((e as Error).message),
  });
  const confirm = useMutation({
    mutationFn: () => api<{ import: ImportJob; job: { id: string } }>(`/api/v1/imports/${imp!.id}/confirm`, { method: "POST" }),
    onSuccess: (r) => {
      setJobId(r.job.id);
      qc.invalidateQueries({ queryKey: [ws, "imports"] });
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const final = useQuery({
    queryKey: [ws, "import", imp?.id, job.data?.status],
    queryFn: () => api<ImportJob>(`/api/v1/imports/${imp!.id}`),
    enabled: !!imp && !!job.data && ["succeeded", "failed"].includes(job.data.status),
  });
  useEffect(() => {
    if (final.data && ["completed", "completed_with_errors", "failed"].includes(final.data.status)) qc.invalidateQueries({ queryKey: [ws] });
  }, [final.data, qc, ws]);

  const onFile = (f: File | undefined) => {
    if (!f) return;
    if (f.size > fields.max_file_mb * 1024 * 1024) {
      toast.error(`File is larger than ${fields.max_file_mb} MB.`);
      return;
    }
    upload.mutate(f);
  };

  return (
    <Card title="Import feedback" description="CSV, XLSX or JSON. Spreadsheet macros and formulas are never executed.">
      <Stepper step={step} />
      {step === 0 && (
        <div className="space-y-4">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              onFile(e.dataTransfer.files[0]);
            }}
            className={cn("flex flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center", dragOver ? "border-accent-600 bg-accent-50" : "border-line")}
          >
            {upload.isPending ? <Loader2 className="h-8 w-8 animate-spin text-muted" /> : <UploadCloud className="h-8 w-8 text-muted" />}
            <p className="mt-3 text-sm font-medium">Drop a file here or choose one</p>
            <p className="mt-1 text-xs text-muted">
              {fields.accepted_types.join(", ")} · up to {fields.max_file_mb} MB · up to {fields.max_rows.toLocaleString()} rows
            </p>
            <input ref={fileRef} type="file" accept=".csv,.xlsx,.json" className="sr-only" aria-label="Choose file" onChange={(e) => onFile(e.target.files?.[0])} />
            <Button className="mt-4" size="sm" onClick={() => fileRef.current?.click()} loading={upload.isPending}>
              Choose file
            </Button>
          </div>
          <Field label="Text encoding (CSV/JSON)" htmlFor="encoding" hint="Automatic: UTF-8, then Windows-1252. Choose explicitly if characters look wrong in the preview." className="max-w-xs">
            <Select id="encoding" value={encoding} onChange={(e) => setEncoding(e.target.value)}>
              <option value="">Automatic</option>
              {fields.encodings.map((e) => (
                <option key={e} value={e}>
                  {e}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      )}

      {imp && step >= 2 && step < 6 && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <FileSpreadsheet className="h-4 w-4 text-muted" />
            <span className="font-medium">{imp.file_name}</span>
            <span className="text-muted">
              {formatBytes(imp.file_size)} · {imp.total_rows.toLocaleString()} rows · {imp.columns.length} columns
              {imp.encoding && ` · encoding ${imp.encoding}`}
              {imp.sheet_name && ` · sheet "${imp.sheet_name}"`}
            </span>
          </div>
          {imp.sample_rows && imp.sample_rows.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-semibold">Step 2 · Columns found (first rows)</h3>
              <div className="max-h-56 overflow-auto rounded-lg border border-line">
                <table className="table-base text-xs">
                  <thead>
                    <tr>
                      {imp.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {imp.sample_rows.slice(0, 5).map((r, i) => (
                      <tr key={i}>
                        {r.map((v, j) => (
                          <td key={j} className="max-w-[16rem] truncate">
                            {v}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          <div>
            <h3 className="mb-2 text-sm font-semibold">Step 3 · Map columns to fields</h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {fields.fields.map((fl) => (
                <Field key={fl.key} label={`${fl.label}${fl.required ? " *" : ""}`} htmlFor={`map-${fl.key}`}>
                  <Select
                    id={`map-${fl.key}`}
                    value={mapping[fl.key] ?? ""}
                    onChange={(e) => {
                      setMapping({ ...mapping, [fl.key]: e.target.value });
                      setValidation(null);
                    }}
                  >
                    <option value="">— not mapped —</option>
                    {imp.columns.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </Select>
                </Field>
              ))}
            </div>
          </div>
          <div>
            <h3 className="mb-2 text-sm font-semibold">Options</h3>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Field label="Date format" htmlFor="date_order" hint="Auto-detected when unambiguous; ambiguous dates are rejected, not guessed.">
                <Select id="date_order" value={opts.date_order} onChange={(e) => setOpts({ ...opts, date_order: e.target.value })}>
                  <option value="auto">Automatic</option>
                  <option value="dayfirst">Day first (31/12/2026)</option>
                  <option value="monthfirst">Month first (12/31/2026)</option>
                </Select>
              </Field>
              <Field label="Rows without a date" htmlFor="missing_date">
                <Select id="missing_date" value={opts.missing_date} onChange={(e) => setOpts({ ...opts, missing_date: e.target.value })}>
                  <option value="reject">Reject the row</option>
                  <option value="use_import_time">Use the import time</option>
                </Select>
              </Field>
              <Field label="Rating scale" htmlFor="rating_scale">
                <Select id="rating_scale" value={opts.rating_scale} onChange={(e) => setOpts({ ...opts, rating_scale: e.target.value })}>
                  <option value="5">0-5</option>
                  <option value="10">0-10</option>
                  <option value="100">0-100</option>
                  <option value="1">0-1</option>
                </Select>
              </Field>
              <Field label="Default source name" htmlFor="default_source" hint="Used when no source column is mapped">
                <input id="default_source" className="input" value={opts.default_source} onChange={(e) => setOpts({ ...opts, default_source: e.target.value })} placeholder={`${imp.file_type.toUpperCase()} import`} />
              </Field>
              <Field label="Default product" htmlFor="default_product">
                <input id="default_product" className="input" value={opts.default_product} onChange={(e) => setOpts({ ...opts, default_product: e.target.value })} />
              </Field>
              <label className="mt-6 flex items-center gap-2 text-sm">
                <input type="checkbox" checked={opts.skip_duplicates} onChange={(e) => setOpts({ ...opts, skip_duplicates: e.target.checked })} className="h-4 w-4 accent-teal-600" />
                Skip duplicates (reported, not imported)
              </label>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => validate.mutate()} loading={validate.isPending} disabled={!mapping.text}>
              Preview & validate
            </Button>
            <Button
              variant="outline"
              onClick={async () => {
                await api(`/api/v1/imports/${imp.id}/cancel`, { method: "POST" }).catch(() => undefined);
                onDone();
              }}
            >
              Cancel import
            </Button>
          </div>

          {validation && (
            <div className="space-y-4 border-t border-line pt-5">
              <h3 className="text-sm font-semibold">Steps 4-5 · Preview and validation</h3>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <div className="rounded-lg bg-slate-50 p-3 text-sm">
                  <div className="text-muted">Rows in file</div>
                  <div className="text-xl font-semibold">{validation.total_rows}</div>
                </div>
                <div className="rounded-lg bg-emerald-50 p-3 text-sm">
                  <div className="text-emerald-800">Will be imported</div>
                  <div className="text-xl font-semibold text-emerald-900">{validation.valid_rows}</div>
                </div>
                <div className="rounded-lg bg-red-50 p-3 text-sm">
                  <div className="text-red-800">Invalid</div>
                  <div className="text-xl font-semibold text-red-900">{validation.invalid_rows}</div>
                </div>
                <div className="rounded-lg bg-amber-50 p-3 text-sm">
                  <div className="text-amber-800">Duplicates ({validation.duplicates_will_be})</div>
                  <div className="text-xl font-semibold text-amber-900">{validation.duplicate_rows}</div>
                </div>
              </div>
              {validation.date_defaulted_rows > 0 && <Notice tone="amber">{validation.date_defaulted_rows} rows have no date and will use the import time. This affects trends.</Notice>}
              {validation.preview.length > 0 && (
                <div className="max-h-64 overflow-auto rounded-lg border border-line">
                  <table className="table-base text-xs">
                    <thead>
                      <tr>
                        <th>Row</th>
                        <th>Text</th>
                        <th>Date (UTC)</th>
                        <th>Product</th>
                        <th>Source</th>
                        <th>Rating</th>
                      </tr>
                    </thead>
                    <tbody>
                      {validation.preview.map((p) => (
                        <tr key={String(p.row_number)}>
                          <td>{String(p.row_number)}</td>
                          <td className="max-w-[24rem] truncate">{String(p.text)}</td>
                          <td className="whitespace-nowrap">{String(p.received_at ?? "").replace("T", " ").slice(0, 16)}</td>
                          <td>{String(p.product ?? "—")}</td>
                          <td>{String(p.source ?? "—")}</td>
                          <td>{p.rating !== undefined ? String(p.rating) : "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {validation.errors.length > 0 && (
                <div>
                  <h4 className="mb-1 text-sm font-medium">Rows that will not be imported (first {validation.errors.length})</h4>
                  <ul className="max-h-48 space-y-1 overflow-auto text-xs">
                    {validation.errors.map((e) => (
                      <li key={`${e.error_type}-${e.row_number}`} className="flex gap-2">
                        <Badge tone={e.error_type === "duplicate" ? "amber" : "red"}>Row {e.row_number}</Badge>
                        <span>{e.message}</span>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-1 text-xs text-muted">The full list of rejected rows can be downloaded after the import.</p>
                </div>
              )}
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="secondary" onClick={() => confirm.mutate()} loading={confirm.isPending} disabled={validation.valid_rows === 0}>
                  Step 6 · Confirm import of {validation.valid_rows} rows
                </Button>
                {validation.valid_rows === 0 && <span className="text-sm text-red-700">No valid rows - adjust the mapping or options.</span>}
              </div>
            </div>
          )}
        </div>
      )}

      {step === 6 && (
        <div className="space-y-4">
          <h3 className="text-sm font-semibold">Step 7 · Processing</h3>
          {job.data && !["succeeded", "failed"].includes(job.data.status) && (
            <div>
              <Progress value={job.data.progress || 5} />
              <p className="mt-2 text-sm text-muted">Importing and analysing records in the background. You can leave this page; the import continues.</p>
            </div>
          )}
          {final.data && (
            <div className="space-y-3">
              {final.data.status === "failed" ? (
                <Notice tone="red" icon={<XCircle className="h-4 w-4" />}>
                  Import failed: {final.data.error_message}. No records were imported.
                </Notice>
              ) : (
                <Notice tone="teal" icon={<CheckCircle2 className="h-4 w-4" />}>
                  Imported {final.data.imported_rows} of {final.data.total_rows} rows. {final.data.invalid_rows} invalid and {final.data.duplicate_rows} duplicate rows were not imported{final.data.invalid_rows + final.data.duplicate_rows > 0 ? " - download the report below." : "."}
                </Notice>
              )}
              <div className="flex flex-wrap gap-2">
                {final.data.invalid_rows + final.data.duplicate_rows > 0 && (
                  <Button variant="outline" size="sm" onClick={() => downloadFile(`/api/v1/imports/${final.data!.id}/errors.csv`, "rejected-rows.csv")}>
                    <Download className="h-3.5 w-3.5" /> Download rejected rows
                  </Button>
                )}
                <Link to="/feedback">
                  <Button size="sm">View feedback</Button>
                </Link>
                <Button size="sm" variant="ghost" onClick={onDone}>
                  Import another file
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

export default function ImportsPage() {
  const ws = useWsKey();
  const { can } = useAuth();
  const fields = useQuery({ queryKey: [ws, "import-fields"], queryFn: () => api<FieldsInfo>("/api/v1/imports/fields") });
  const history = useQuery({ queryKey: [ws, "imports"], queryFn: () => api<ImportJob[]>("/api/v1/imports"), refetchInterval: 5000 });
  const [resume, setResume] = useState<ImportJob | null>(null);
  const [wizardKey, setWizardKey] = useState(0);

  return (
    <div>
      <PageHeader title="Imports" description="Guided import: upload, inspect columns, map fields, preview, validate, confirm and process." />
      <div className="space-y-5">
        {can("imports:manage") ? (
          fields.data ? (
            <Wizard
              key={wizardKey}
              fields={fields.data}
              initial={resume}
              onDone={() => {
                setResume(null);
                setWizardKey((k) => k + 1);
              }}
            />
          ) : fields.isError ? (
            <ErrorState error={fields.error} />
          ) : (
            <LoadingBlock />
          )
        ) : (
          <Notice tone="blue">Your role can view import history but not import data.</Notice>
        )}
        <Card title="Import history">
          {history.isLoading && <LoadingBlock />}
          {history.data?.length === 0 && <EmptyState title="No imports yet" />}
          {history.data && history.data.length > 0 && (
            <div className="overflow-x-auto">
              <table className="table-base">
                <thead>
                  <tr>
                    <th>File</th>
                    <th>Status</th>
                    <th>Rows</th>
                    <th>Imported</th>
                    <th>Rejected</th>
                    <th>Uploaded</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {history.data.map((h) => (
                    <tr key={h.id}>
                      <td className="font-medium">{h.file_name}</td>
                      <td>
                        <Badge tone={IMPORT_STATUS[h.status]?.tone ?? "slate"}>{IMPORT_STATUS[h.status]?.label ?? h.status}</Badge>
                      </td>
                      <td>{h.total_rows}</td>
                      <td>{h.imported_rows}</td>
                      <td>{h.status.startsWith("completed") || h.status === "failed" ? h.invalid_rows + h.duplicate_rows : "—"}</td>
                      <td className="whitespace-nowrap text-muted">{formatDateTime(h.created_at)}</td>
                      <td className="whitespace-nowrap text-right">
                        {(h.status === "uploaded" || h.status === "validated") && can("imports:manage") && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={async () => {
                              const full = await api<ImportJob>(`/api/v1/imports/${h.id}`);
                              setResume(full);
                              setWizardKey((k) => k + 1);
                              window.scrollTo({ top: 0, behavior: "smooth" });
                            }}
                          >
                            Continue
                          </Button>
                        )}
                        {h.invalid_rows + h.duplicate_rows > 0 && h.status.startsWith("completed") && (
                          <Button size="sm" variant="ghost" onClick={() => downloadFile(`/api/v1/imports/${h.id}/errors.csv`, "rejected-rows.csv")}>
                            <Download className="h-3.5 w-3.5" /> Rejected rows
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
