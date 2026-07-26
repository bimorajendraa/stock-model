import Link from "next/link";

export function Nav() {
  return (
    <header className="border-b border-black/10 dark:border-white/10">
      <nav className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-4">
        <Link href="/" className="font-semibold">
          IDX Investment Intelligence
        </Link>
        <Link href="/" className="text-sm text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100">
          Companies
        </Link>
        <Link
          href="/recommendations"
          className="text-sm text-gray-600 hover:text-gray-900 dark:text-gray-400 dark:hover:text-gray-100"
        >
          Recommendations
        </Link>
      </nav>
    </header>
  );
}
