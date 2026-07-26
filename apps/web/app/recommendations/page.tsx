import Link from "next/link";
import { listRecommendations } from "@/lib/api";
import { RecommendationBadge } from "@/components/RecommendationBadge";

const LABELS = ["LAYAK_DIBELI", "AKUMULASI_BERTAHAP", "HOLD", "TUNGGU_HARGA", "HINDARI", "DATA_TIDAK_MENCUKUPI"];

export default async function RecommendationsPage({
  searchParams,
}: {
  searchParams: Promise<{ label?: string }>;
}) {
  const { label } = await searchParams;
  const data = await listRecommendations({ label, limit: 200 });

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold">Recommendation screener</h1>
      <p className="mb-4 text-sm text-gray-500 dark:text-gray-400">
        Deterministic, non-ML recommendation engine (see the company page for how each label was reached) --{" "}
        {data.total} companies currently have a computed recommendation, sorted by confidence.
      </p>

      <div className="mb-4 flex flex-wrap gap-2">
        <Link
          href="/recommendations"
          className={`rounded-full px-3 py-1 text-xs ${
            !label ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "border border-black/15 dark:border-white/20"
          }`}
        >
          All
        </Link>
        {LABELS.map((l) => (
          <Link
            key={l}
            href={`/recommendations?label=${l}`}
            className={`rounded-full px-3 py-1 text-xs ${
              label === l ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "border border-black/15 dark:border-white/20"
            }`}
          >
            {l.replaceAll("_", " ")}
          </Link>
        ))}
      </div>

      <div className="overflow-x-auto rounded border border-black/10 dark:border-white/10">
        <table className="w-full text-left text-sm">
          <thead className="bg-black/5 dark:bg-white/5">
            <tr>
              <th className="px-3 py-2 font-medium">Ticker</th>
              <th className="px-3 py-2 font-medium">Company</th>
              <th className="px-3 py-2 font-medium">Label</th>
              <th className="px-3 py-2 font-medium">Confidence</th>
              <th className="px-3 py-2 font-medium">As of</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((r) => (
              <tr key={r.ticker} className="border-t border-black/5 dark:border-white/5">
                <td className="px-3 py-2 font-mono">
                  <Link href={`/companies/${r.ticker}`} className="text-blue-600 hover:underline dark:text-blue-400">
                    {r.ticker}
                  </Link>
                </td>
                <td className="px-3 py-2">{r.company_name}</td>
                <td className="px-3 py-2">
                  <RecommendationBadge label={r.label} />
                </td>
                <td className="px-3 py-2">{r.confidence.toFixed(4)}</td>
                <td className="px-3 py-2 text-gray-500 dark:text-gray-400">{r.as_of_date}</td>
              </tr>
            ))}
            {data.items.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-gray-500">
                  No companies with this label.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
