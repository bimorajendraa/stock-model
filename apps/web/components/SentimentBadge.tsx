const SENTIMENT_STYLES: Record<string, string> = {
  sangat_positif: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  positif: "bg-lime-100 text-lime-800 dark:bg-lime-900/40 dark:text-lime-300",
  netral: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  negatif: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
  sangat_negatif: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
};

export function SentimentBadge({ label }: { label: string | null }) {
  if (!label) {
    return <span className="text-xs text-gray-400">belum discore</span>;
  }
  const style = SENTIMENT_STYLES[label] ?? SENTIMENT_STYLES.netral;
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${style}`}>
      {label.replaceAll("_", " ")}
    </span>
  );
}
