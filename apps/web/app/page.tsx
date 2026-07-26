import Link from "next/link";
import { listCompanies } from "@/lib/api";

const PAGE_SIZE = 50;

export default async function HomePage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; offset?: string }>;
}) {
  const { q, offset: offsetParam } = await searchParams;
  const offset = Number(offsetParam ?? 0) || 0;

  const data = await listCompanies({ q, offset, limit: PAGE_SIZE });
  const hasPrev = offset > 0;
  const hasNext = offset + data.items.length < data.total;

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold">Companies</h1>
      <p className="mb-4 text-sm text-gray-500 dark:text-gray-400">
        {data.total} real IDX-listed companies. Fundamental/valuation/recommendation data currently only covers
        the top-50-by-market-cap set -- see a company&apos;s page for what&apos;s actually computed for it.
      </p>

      <form className="mb-4 flex gap-2" action="/">
        <input
          type="text"
          name="q"
          defaultValue={q ?? ""}
          placeholder="Search ticker or company name..."
          className="w-full max-w-sm rounded border border-black/15 bg-transparent px-3 py-1.5 text-sm dark:border-white/20"
        />
        <button
          type="submit"
          className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white dark:bg-slate-100 dark:text-slate-900"
        >
          Search
        </button>
      </form>

      <div className="overflow-x-auto rounded border border-black/10 dark:border-white/10">
        <table className="w-full text-left text-sm">
          <thead className="bg-black/5 dark:bg-white/5">
            <tr>
              <th className="px-3 py-2 font-medium">Ticker</th>
              <th className="px-3 py-2 font-medium">Company</th>
              <th className="px-3 py-2 font-medium">Sector</th>
              <th className="px-3 py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((c) => (
              <tr key={c.ticker} className="border-t border-black/5 dark:border-white/5">
                <td className="px-3 py-2 font-mono">
                  <Link href={`/companies/${c.ticker}`} className="text-blue-600 hover:underline dark:text-blue-400">
                    {c.ticker}
                  </Link>
                </td>
                <td className="px-3 py-2">{c.company_name}</td>
                <td className="px-3 py-2 text-gray-500 dark:text-gray-400">{c.sector_name ?? "—"}</td>
                <td className="px-3 py-2 text-gray-500 dark:text-gray-400">{c.status}</td>
              </tr>
            ))}
            {data.items.length === 0 && (
              <tr>
                <td colSpan={4} className="px-3 py-6 text-center text-gray-500">
                  No companies match &quot;{q}&quot;.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-4 flex justify-between text-sm">
        <Link
          href={`/?q=${encodeURIComponent(q ?? "")}&offset=${Math.max(0, offset - PAGE_SIZE)}`}
          aria-disabled={!hasPrev}
          className={hasPrev ? "text-blue-600 hover:underline dark:text-blue-400" : "pointer-events-none text-gray-400"}
        >
          ← Previous
        </Link>
        <span className="text-gray-500 dark:text-gray-400">
          Showing {offset + 1}-{offset + data.items.length} of {data.total}
        </span>
        <Link
          href={`/?q=${encodeURIComponent(q ?? "")}&offset=${offset + PAGE_SIZE}`}
          aria-disabled={!hasNext}
          className={hasNext ? "text-blue-600 hover:underline dark:text-blue-400" : "pointer-events-none text-gray-400"}
        >
          Next →
        </Link>
      </div>
    </div>
  );
}
