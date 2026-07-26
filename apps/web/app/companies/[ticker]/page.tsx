import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, getCompanyNews, getCompanySnapshot } from "@/lib/api";
import { RecommendationBadge } from "@/components/RecommendationBadge";
import { SentimentBadge } from "@/components/SentimentBadge";

function fmtNumber(value: number | null, digits = 2): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

function fmtIdr(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return `Rp ${value.toLocaleString("id-ID", { maximumFractionDigits: 2 })}`;
}

export default async function CompanyPage({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = await params;

  let snapshot;
  try {
    snapshot = await getCompanySnapshot(ticker);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }
  const news = await getCompanyNews(ticker, { limit: 10 });

  const { company, technical, fundamental_ratios, sector_relative_metrics, valuation, recommendation } = snapshot;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">
          {company.ticker} <span className="font-normal text-gray-500 dark:text-gray-400">— {company.company_name}</span>
        </h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">
          {company.sector_name ?? "Sector not classified"}
          {company.subsector_name ? ` — ${company.subsector_name}` : ""} · {company.status}
        </p>
      </div>

      <div className="mb-6 grid gap-4 sm:grid-cols-2">
        <section className="rounded border border-black/10 p-4 dark:border-white/10">
          <h2 className="mb-2 text-sm font-semibold text-gray-500 dark:text-gray-400">Recommendation</h2>
          {recommendation ? (
            <div>
              <div className="mb-2 flex items-center gap-2">
                <RecommendationBadge label={recommendation.label} />
                <span className="text-xs text-gray-500 dark:text-gray-400">
                  confidence {fmtNumber(recommendation.confidence, 2)} · as of {recommendation.as_of_date}
                </span>
              </div>
              {recommendation.entry_zone && (
                <p className="text-sm">
                  Entry zone: {fmtIdr(recommendation.entry_zone.low)} – {fmtIdr(recommendation.entry_zone.high)}
                </p>
              )}
              {recommendation.suggested_horizon && (
                <p className="text-sm text-gray-500 dark:text-gray-400">Horizon: {recommendation.suggested_horizon}</p>
              )}
              {recommendation.guardrails_triggered && recommendation.guardrails_triggered.length > 0 && (
                <p className="mt-2 text-sm text-amber-600 dark:text-amber-400">
                  Guardrails: {recommendation.guardrails_triggered.join(", ")}
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-gray-400">No recommendation computed for this company yet.</p>
          )}
        </section>

        <section className="rounded border border-black/10 p-4 dark:border-white/10">
          <h2 className="mb-2 text-sm font-semibold text-gray-500 dark:text-gray-400">Valuation (self-relative)</h2>
          {valuation ? (
            <div className="text-sm">
              <p className="mb-1 text-xs text-gray-500 dark:text-gray-400">as of {valuation.as_of_date}</p>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1">
                <dt className="text-gray-500 dark:text-gray-400">Bear</dt>
                <dd>{fmtIdr(valuation.fair_value_bear)}</dd>
                <dt className="text-gray-500 dark:text-gray-400">Base</dt>
                <dd>{fmtIdr(valuation.fair_value_base)}</dd>
                <dt className="text-gray-500 dark:text-gray-400">Bull</dt>
                <dd>{fmtIdr(valuation.fair_value_bull)}</dd>
                <dt className="text-gray-500 dark:text-gray-400">Conservative</dt>
                <dd>{fmtIdr(valuation.fair_value_conservative)}</dd>
              </dl>
              <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
                Data quality: {fmtNumber(valuation.data_quality_score, 2)}
              </p>
            </div>
          ) : (
            <p className="text-sm text-gray-400">No valuation computed for this company yet.</p>
          )}
        </section>
      </div>

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <NamedValueTable title="Technical" values={technical} />
        <NamedValueTable title="Fundamental ratios" values={fundamental_ratios} />
        <NamedValueTable title="Sector-relative metrics" values={sector_relative_metrics} />
      </div>

      <section>
        <h2 className="mb-2 text-sm font-semibold text-gray-500 dark:text-gray-400">
          Recent news ({news.total} entity-linked article{news.total === 1 ? "" : "s"})
        </h2>
        {news.items.length === 0 ? (
          <p className="text-sm text-gray-400">No entity-linked news for this company yet.</p>
        ) : (
          <ul className="space-y-2">
            {news.items.map((item) => (
              <li key={item.canonical_url} className="rounded border border-black/10 p-3 text-sm dark:border-white/10">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <SentimentBadge label={item.sentiment_label} />
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {item.media_name} · tier {item.credibility_tier} ·{" "}
                    {item.published_at ? new Date(item.published_at).toLocaleDateString("en-CA") : "date unknown"}
                  </span>
                </div>
                <Link
                  href={item.canonical_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-blue-600 hover:underline dark:text-blue-400"
                >
                  {item.title}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function NamedValueTable({ title, values }: { title: string; values: { name: string; value: number | null }[] }) {
  return (
    <section className="rounded border border-black/10 p-4 dark:border-white/10">
      <h2 className="mb-2 text-sm font-semibold text-gray-500 dark:text-gray-400">
        {title} ({values.length})
      </h2>
      {values.length === 0 ? (
        <p className="text-sm text-gray-400">Not computed for this company yet.</p>
      ) : (
        <div className="max-h-64 overflow-y-auto">
          <table className="w-full text-left text-xs">
            <tbody>
              {values.map((v) => (
                <tr key={v.name} className="border-t border-black/5 first:border-t-0 dark:border-white/5">
                  <td className="py-1 pr-2 font-mono text-gray-500 dark:text-gray-400">{v.name}</td>
                  <td className="py-1 text-right">{fmtNumber(v.value, 4)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
