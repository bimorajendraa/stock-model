// Typed fetch helpers for the FastAPI backend (docs/api.md). Types here
// mirror apps/api/schemas.py exactly -- this dashboard adds no business
// logic of its own, it only renders what that read-only API already
// serializes.

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function apiFetch<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export type CompanyListItem = {
  ticker: string;
  company_name: string;
  asset_type: string;
  sector_name: string | null;
  listing_board: string | null;
  status: string;
};

export type CompanyListResponse = {
  items: CompanyListItem[];
  total: number;
  offset: number;
  limit: number;
};

export type CompanyDetail = {
  ticker: string;
  company_name: string;
  asset_type: string;
  sector_name: string | null;
  subsector_name: string | null;
  listing_board: string | null;
  listing_date: string | null;
  status: string;
};

export type NamedValue = {
  name: string;
  value: number | null;
  as_of: string | null;
};

export type ValuationSnapshot = {
  as_of_date: string;
  methods_used: Record<string, number>;
  fair_value_bear: number | null;
  fair_value_base: number | null;
  fair_value_bull: number | null;
  fair_value_conservative: number | null;
  data_quality_score: number | null;
};

export type RecommendationSnapshot = {
  as_of_date: string;
  label: string;
  confidence: number;
  scores: Record<string, unknown>;
  guardrails_triggered: string[] | null;
  entry_zone: { low: number; high: number } | null;
  investment_style: string | null;
  suggested_horizon: string | null;
};

export type CompanySnapshot = {
  company: CompanyDetail;
  technical: NamedValue[];
  fundamental_ratios: NamedValue[];
  sector_relative_metrics: NamedValue[];
  valuation: ValuationSnapshot | null;
  recommendation: RecommendationSnapshot | null;
};

export type NewsItem = {
  title: string;
  media_name: string;
  canonical_url: string;
  published_at: string | null;
  credibility_tier: number;
  sentiment_label: string | null;
  sentiment_score: number | null;
};

export type NewsListResponse = {
  items: NewsItem[];
  total: number;
  offset: number;
  limit: number;
};

export type RecommendationScreenerItem = {
  ticker: string;
  company_name: string;
  as_of_date: string;
  label: string;
  confidence: number;
};

export type RecommendationScreenerResponse = {
  items: RecommendationScreenerItem[];
  total: number;
  offset: number;
  limit: number;
};

export function listCompanies(
  params: {
    q?: string;
    asset_type?: "equity" | "index" | "etf" | "other" | "all";
    offset?: number;
    limit?: number;
  } = {},
) {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.asset_type) qs.set("asset_type", params.asset_type);
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<CompanyListResponse>(`/api/v1/companies${suffix}`);
}

export function getCompany(ticker: string) {
  return apiFetch<CompanyDetail>(`/api/v1/companies/${encodeURIComponent(ticker)}`);
}

export function getCompanySnapshot(ticker: string) {
  return apiFetch<CompanySnapshot>(`/api/v1/companies/${encodeURIComponent(ticker)}/snapshot`);
}

export function getCompanyNews(ticker: string, params: { offset?: number; limit?: number } = {}) {
  const qs = new URLSearchParams();
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<NewsListResponse>(`/api/v1/companies/${encodeURIComponent(ticker)}/news${suffix}`);
}

export function listRecommendations(params: { label?: string; offset?: number; limit?: number } = {}) {
  const qs = new URLSearchParams();
  if (params.label) qs.set("label", params.label);
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiFetch<RecommendationScreenerResponse>(`/api/v1/recommendations${suffix}`);
}
