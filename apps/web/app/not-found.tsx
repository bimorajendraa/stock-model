import Link from "next/link";

export default function NotFound() {
  return (
    <div className="py-16 text-center">
      <h1 className="mb-2 text-xl font-semibold">Not found</h1>
      <p className="mb-4 text-sm text-gray-500 dark:text-gray-400">
        No company with that ticker exists in the database.
      </p>
      <Link href="/" className="text-blue-600 hover:underline dark:text-blue-400">
        ← Back to companies
      </Link>
    </div>
  );
}
