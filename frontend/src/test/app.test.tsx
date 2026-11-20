import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App from "@/App";
import { qs } from "@/lib/api";
import { mockFetch, renderWithProviders } from "./utils";

const ME = {
  id: "u1",
  email: "a@example.com",
  full_name: "Ada Analyst",
  created_at: null,
  workspaces: [{ id: "w1", name: "Acme", role: "owner", timezone: "UTC", permissions: ["feedback:read", "feedback:write", "demo:manage", "imports:manage", "ai_settings:manage"] }],
};

const DIST = {
  total: 10,
  classified: 7,
  unclassified: 3,
  counts: { positive: 3, negative: 2, neutral: 1, mixed: 1, uncertain: 0 },
  percentages: { positive: 42.9, negative: 28.6, neutral: 14.3, mixed: 14.3, uncertain: 0 },
  average_score: 0.083,
  average_score_n: 6,
  average_rating_pct: null,
  average_rating_n: 0,
  methods: { lexicon: 0, ai: 6, manual: 1 },
  denominator_note: "Percentages are shares of classified records.",
};

function overview(extra: Record<string, unknown> = {}) {
  return {
    filters: {},
    data_range: { earliest: "2026-01-01", latest: "2026-01-31" },
    distribution: DIST,
    timeseries: { granularity: "day", buckets: [], min_bucket_size: 5 },
    trend: { metric: "negative_share", status: "insufficient_data", points_used: 0, note: "Needs more data." },
    topics: [],
    by_source: [],
    by_product: [],
    emotions: [],
    emerging: [],
    emerging_period: null,
    insights: [],
    alerts: [],
    activity: [],
    demo_records: 0,
    ai: { provider: "none", model: "", source: "environment", configured: false, api_key_set: false, message: "AI is not configured" },
    min_sample_size: 5,
    ...extra,
  };
}

const COMMON = {
  "GET /api/v1/auth/me": { body: ME },
  "GET /api/v1/alerts/events": { body: { unread: 0, items: [] } },
  "GET /api/v1/products": { body: [] },
  "GET /api/v1/sources": { body: [] },
};

function signedIn() {
  localStorage.setItem("fm.session", JSON.stringify({ access_token: "a", refresh_token: "r", expires_in: 900 }));
}

const FEEDBACK_ITEM = {
  id: "f1",
  text: "<img src=x onerror=alert(1)> broken",
  title: null,
  received_at: "2026-01-02T00:00:00Z",
  source: null,
  product: null,
  customer_ref: null,
  customer_segment: null,
  language: "en",
  rating: null,
  rating_max: null,
  sentiment: { label: "negative", score: -0.5, confidence: null, method: "lexicon" },
  primary_emotion: null,
  topics: [],
  tags: [],
  processing_status: "processed",
  ai_status: "not_requested",
  needs_review: false,
  is_archived: false,
  is_demo: false,
  external_id: null,
  created_at: "",
  updated_at: "",
};

describe("FeedbackMind frontend", () => {
  it("redirects anonymous users to the login page and validates the form", async () => {
    mockFetch({});
    renderWithProviders(<App />, { route: "/" });
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument();
  });

  it("shows login errors from the API", async () => {
    mockFetch({ "POST /api/v1/auth/login": { status: 401, body: { detail: "Invalid email or password." } } });
    renderWithProviders(<App />, { route: "/login" });
    await userEvent.type(screen.getByLabelText("Email"), "a@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Invalid email or password.")).toBeInTheDocument();
  });

  it("renders dashboard figures from the API with AI-unavailable and denominator notes", async () => {
    signedIn();
    const fetch = mockFetch({ ...COMMON, "GET /api/v1/analytics/overview": { body: overview() } });
    renderWithProviders(<App />, { route: "/" });
    expect((await screen.findAllByText("42.9%")).length).toBeGreaterThan(0); // stat card + chart legend
    expect(screen.getAllByText("28.6%").length).toBeGreaterThan(0);
    expect(screen.getByText(/7 classified · 3 unclassified/)).toBeInTheDocument();
    expect(screen.getByText(/AI analysis is not configured/)).toBeInTheDocument();
    expect(screen.getByText(/Percentages are shares of classified records/)).toBeInTheDocument();
    const call = fetch.mock.calls.find(([u]) => String(u).includes("/analytics/overview"));
    expect((call?.[1] as RequestInit).headers).toMatchObject({ "X-Workspace-ID": "w1" });
  });

  it("labels demo data and offers removal", async () => {
    signedIn();
    mockFetch({ ...COMMON, "GET /api/v1/analytics/overview": { body: overview({ demo_records: 240 }) } });
    renderWithProviders(<App />, { route: "/" });
    expect(await screen.findByText(/240 synthetic demo records/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove demo data" })).toBeInTheDocument();
  });

  it("shows an empty state with import and sample-data actions for new workspaces", async () => {
    signedIn();
    mockFetch({
      ...COMMON,
      "GET /api/v1/analytics/overview": { body: overview({ data_range: { earliest: null, latest: null }, distribution: { ...DIST, total: 0, classified: 0, unclassified: 0 } }) },
    });
    renderWithProviders(<App />, { route: "/" });
    expect(await screen.findByText("No feedback yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Import data/ })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Load sample dataset/ }).length).toBeGreaterThan(0);
  });

  it("renders feedback text as text, never as HTML, and labels the method", async () => {
    signedIn();
    mockFetch({ ...COMMON, "GET /api/v1/feedback": { body: { total: 1, limit: 25, offset: 0, items: [FEEDBACK_ITEM] } } });
    const { container } = renderWithProviders(<App />, { route: "/feedback" });
    expect(await screen.findByText(FEEDBACK_ITEM.text)).toBeInTheDocument();
    expect(container.querySelector("img[src='x']")).toBeNull();
    expect(screen.getByText("Rule-based (not AI)")).toBeInTheDocument();
  });

  it("builds query strings with repeated keys and skips empty values", () => {
    expect(qs({ a: "1", b: "", c: undefined, d: ["x", "y"] })).toBe("?a=1&d=x&d=y");
  });

  it("shows the import wizard with limits from the API", async () => {
    signedIn();
    mockFetch({
      ...COMMON,
      "GET /api/v1/imports/fields": { body: { fields: [{ key: "text", label: "Feedback text", required: true }], max_file_mb: 20, max_rows: 100000, accepted_types: [".csv", ".xlsx", ".json"], encodings: ["utf-8"] } },
      "GET /api/v1/imports": { body: [] },
    });
    renderWithProviders(<App />, { route: "/imports" });
    await waitFor(() => expect(screen.getByText("Drop a file here or choose one")).toBeInTheDocument());
    expect(screen.getByText(/up to 20 MB/)).toBeInTheDocument();
  });
});
