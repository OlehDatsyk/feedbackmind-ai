export type Role = "owner" | "admin" | "analyst" | "viewer";
export type SentimentLabel = "positive" | "negative" | "neutral" | "mixed" | "uncertain";
export type Method = "lexicon" | "ai" | "manual";

export interface WorkspaceRef {
  id: string;
  name: string;
  role: Role;
  timezone: string;
  permissions: string[];
}

export interface Me {
  id: string;
  email: string;
  full_name: string;
  created_at: string | null;
  workspaces: WorkspaceRef[];
}

export interface Workspace extends WorkspaceRef {
  description: string;
  industry: string;
  created_at: string | null;
}

export interface Named {
  id: string;
  name: string;
}

export interface Product extends Named {
  description: string;
  feedback_count: number;
}
export interface Source extends Named {
  kind: string;
  feedback_count: number;
}

export interface FeedbackTopicRef extends Named {
  sentiment: SentimentLabel | null;
  assigned_by: "rule" | "ai" | "manual";
  evidence?: string | null;
}

export interface Feedback {
  id: string;
  text: string;
  title: string | null;
  received_at: string;
  source: (Named & { kind: string }) | null;
  product: Named | null;
  customer_ref: string | null;
  customer_segment: string | null;
  language: string | null;
  rating: number | null;
  rating_max: number | null;
  sentiment: { label: SentimentLabel | null; score: number | null; confidence: number | null; method: Method | null };
  primary_emotion: string | null;
  topics: FeedbackTopicRef[];
  tags: Named[];
  processing_status: string;
  ai_status: string;
  needs_review: boolean;
  is_archived: boolean;
  is_demo: boolean;
  external_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Analysis {
  id: string;
  method: Method;
  label: SentimentLabel;
  score: number | null;
  confidence: number | null;
  explanation: string;
  evidence: string[];
  language: string | null;
  provider: string | null;
  model: string | null;
  previous_label: string | null;
  corrected_by: string | null;
  created_at: string;
}

export interface FeedbackDetail extends Feedback {
  analyses: Analysis[];
  emotions: { id: string; method: string; emotions: { emotion: string; confidence: number | null; evidence: string[] }[]; primary_emotion: string | null; explanation: string; model: string | null; created_at: string }[];
  notes: { id: string; body: string; author: string | null; created_at: string }[];
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Distribution {
  total: number;
  classified: number;
  unclassified: number;
  counts: Record<SentimentLabel, number>;
  percentages: Record<SentimentLabel, number | null>;
  average_score: number | null;
  average_score_n: number;
  average_rating_pct: number | null;
  average_rating_n: number;
  methods: Record<Method, number>;
  denominator_note: string;
}

export interface Bucket {
  bucket: string;
  total: number;
  classified: number;
  positive: number;
  negative: number;
  neutral: number;
  mixed: number;
  uncertain: number;
  negative_share: number | null;
  positive_share: number | null;
  average_score: number | null;
  low_sample: boolean;
}

export interface Series {
  granularity: "day" | "week" | "month";
  buckets: Bucket[];
  min_bucket_size: number;
}

export interface StatTrend {
  metric: string;
  status: "ok" | "insufficient_data";
  direction?: "up" | "down" | "flat";
  slope_per_bucket?: number;
  p_value?: number;
  r_squared?: number;
  points_used: number;
  significant?: boolean;
  method?: string;
  note: string;
}

export interface TopicStat {
  id: string;
  name: string;
  origin: string;
  review_status: string;
  count: number;
  positive: number;
  negative: number;
  neutral: number;
  mixed: number;
  uncertain: number;
  unclassified: number;
  negative_share: number | null;
  positive_share: number | null;
  low_sample: boolean;
}

export interface BreakdownRow {
  id: string | null;
  name: string;
  count: number;
  classified: number;
  counts: Record<SentimentLabel, number>;
  negative_share: number | null;
  positive_share: number | null;
  average_score: number | null;
  low_sample: boolean;
}

export interface AIInfo {
  provider: string;
  model: string;
  source: string;
  configured: boolean;
  api_key_set: boolean;
  message: string | null;
}

export interface Insight {
  id: string;
  kind: string;
  title: string;
  description: string;
  topic: { id: string; name: string | null } | null;
  product: { id: string; name: string | null } | null;
  supporting_count: number;
  period_start: string | null;
  period_end: string | null;
  trend_direction: "up" | "down" | "flat" | "insufficient_data";
  importance: "high" | "medium" | "low";
  evidence_strength: "strong" | "moderate" | "limited";
  suggested_action: string;
  statistics: Record<string, unknown>;
  generated_by: string;
  ai_summary: string | null;
  ai_suggested_action: string | null;
  ai_provider: string | null;
  ai_model: string | null;
  status: string;
  created_at: string;
  evidence: Feedback[] | null;
}

export interface AlertEvent {
  id: string;
  rule_id: string | null;
  alert_type: string;
  title: string;
  explanation: string;
  severity: string;
  metrics: Record<string, unknown>;
  evidence_ids: string[];
  window_start: string | null;
  window_end: string | null;
  status: "open" | "acknowledged" | "resolved";
  is_read: boolean;
  triggered_at: string;
}

export interface EmergingTopic {
  id: string;
  name: string;
  current_count: number;
  previous_count: number;
  current_negative_share: number | null;
  previous_negative_share: number | null;
  is_new: boolean;
  p_value: number | null;
}

export interface Overview {
  filters: Record<string, unknown>;
  data_range: { earliest: string | null; latest: string | null };
  distribution: Distribution;
  timeseries: Series;
  trend: StatTrend;
  topics: TopicStat[];
  by_source: BreakdownRow[];
  by_product: BreakdownRow[];
  emotions: { emotion: string; count: number }[];
  emerging: EmergingTopic[];
  emerging_period: { from: string; to: string } | null;
  insights: Insight[];
  alerts: AlertEvent[];
  activity: { id: string; action: string; summary: string; user: string | null; created_at: string }[];
  demo_records: number;
  ai: AIInfo;
  min_sample_size: number;
}

export interface Job {
  id: string;
  job_type: string;
  status: "queued" | "running" | "succeeded" | "failed";
  progress: number;
  attempts: number;
  max_attempts: number;
  result: Record<string, unknown>;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface ImportJob {
  id: string;
  file_name: string;
  file_type: string;
  file_size: number;
  encoding: string | null;
  sheet_name: string | null;
  columns: string[];
  mapping: Record<string, string>;
  options: Record<string, unknown>;
  status: string;
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  duplicate_rows: number;
  imported_rows: number;
  error_message: string | null;
  job_id: string | null;
  created_at: string;
  completed_at: string | null;
  sample_rows?: string[][];
  job?: Job | null;
}

export interface TopicRow {
  id: string;
  name: string;
  description: string;
  keywords: string[];
  origin: string;
  review_status: "approved" | "pending_review";
  is_active: boolean;
  merged_into_id: string | null;
  created_at: string;
  stats: TopicStat | null;
}

export interface Report {
  id: string;
  title: string;
  format: "pdf" | "docx" | "xlsx" | "csv";
  status: "queued" | "running" | "ready" | "failed";
  parameters: { filters?: Record<string, unknown> };
  file_name: string | null;
  size_bytes: number | null;
  record_count: number | null;
  includes_ai: boolean;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface AlertRule {
  id: string;
  name: string;
  alert_type: string;
  threshold: number;
  window_days: number;
  min_count: number;
  product_id: string | null;
  topic_id: string | null;
  is_enabled: boolean;
  cooldown_hours: number;
  last_evaluated_at: string | null;
  last_triggered_at: string | null;
  created_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: string[];
  facts: Record<string, unknown> & { period?: { label: string; from: string | null; to: string | null }; sample_size?: number; classified?: number; data_sufficient?: boolean };
  ai_generated: boolean;
  provider: string | null;
  model: string | null;
  created_at: string;
}
