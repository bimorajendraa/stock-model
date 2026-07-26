const LABEL_STYLES: Record<string, string> = {
  LAYAK_DIBELI: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  AKUMULASI_BERTAHAP: "bg-lime-100 text-lime-800 dark:bg-lime-900/40 dark:text-lime-300",
  HOLD: "bg-slate-100 text-slate-800 dark:bg-slate-800 dark:text-slate-300",
  TUNGGU_HARGA: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  HINDARI: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  DATA_TIDAK_MENCUKUPI: "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400",
};

export function RecommendationBadge({ label }: { label: string }) {
  const style = LABEL_STYLES[label] ?? LABEL_STYLES.DATA_TIDAK_MENCUKUPI;
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${style}`}>
      {label.replaceAll("_", " ")}
    </span>
  );
}
