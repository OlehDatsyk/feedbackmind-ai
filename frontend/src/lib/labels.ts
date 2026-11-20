import type { Tone } from "@/components/ui";

export const SENTIMENTS = ["positive", "negative", "neutral", "mixed", "uncertain"] as const;

/** Chart colours: validated for contrast on white and distinguishable for common colour-vision deficiencies. */
export const SENTIMENT_COLORS: Record<string, string> = {
  positive: "#0d9488",
  negative: "#dc2626",
  neutral: "#64748b",
  mixed: "#d97706",
  uncertain: "#a78bfa",
};

export const SENTIMENT_TONES: Record<string, Tone> = {
  positive: "green",
  negative: "red",
  neutral: "slate",
  mixed: "amber",
  uncertain: "violet",
};

export const METHOD_LABELS: Record<string, string> = {
  lexicon: "Rule-based (not AI)",
  ai: "AI",
  manual: "Manual correction",
  keyword: "Keyword cues (not AI)",
};

export const ROLE_LABELS: Record<string, string> = { owner: "Owner", admin: "Administrator", analyst: "Analyst", viewer: "Viewer" };

export const IMPORT_STATUS: Record<string, { label: string; tone: Tone }> = {
  uploaded: { label: "Uploaded", tone: "slate" },
  validated: { label: "Validated", tone: "blue" },
  queued: { label: "Queued", tone: "blue" },
  processing: { label: "Processing", tone: "blue" },
  completed: { label: "Completed", tone: "green" },
  completed_with_errors: { label: "Completed with rejected rows", tone: "amber" },
  failed: { label: "Failed", tone: "red" },
  cancelled: { label: "Cancelled", tone: "slate" },
};

export const INSIGHT_KINDS: Record<string, string> = {
  recurring_issue: "Recurring issue",
  rising_negative: "Rising negative feedback",
  positive_driver: "What customers value",
  product_hotspot: "Product hotspot",
  emerging_topic: "Emerging theme",
};

export function titleCase(s: string): string {
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function fmtPct(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${v}%`;
}

export function fmtScore(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : `${v > 0 ? "+" : ""}${v.toFixed(2)}`;
}
