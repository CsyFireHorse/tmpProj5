import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import { api } from "./api/client";
import { SearchDialog } from "./components/SearchDialog";
import { Sidebar } from "./components/Sidebar";
import { useIndexEvents } from "./hooks/useIndexEvents";
import { SessionRoute } from "./routes/SessionRoute";
import { StatsRoute } from "./routes/StatsRoute";
import { WelcomeRoute } from "./routes/WelcomeRoute";

export function App() {
  const [searchOpen, setSearchOpen] = useState(false);
  const location = useLocation();

  // Progress arrives over SSE; the query is only the initial snapshot.
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const liveIndex = useIndexEvents();

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
      if (event.key === "Escape") setSearchOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const index = liveIndex ?? status.data?.index ?? null;
  const indexing = index?.running ?? false;

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center gap-3 border-b border-stone-200 px-4 py-2 dark:border-stone-800">
        <Link to="/" className="text-sm font-semibold">
          Agent Chat Viewer
        </Link>
        <span className="rounded bg-stone-200 px-1.5 py-0.5 text-[0.625rem] muted dark:bg-stone-800">
          local · read-only
        </span>
        <nav className="ml-auto flex items-center gap-3 text-xs">
          <Link
            to="/stats"
            className={location.pathname === "/stats" ? "font-medium" : "muted hover:underline"}
          >
            Usage
          </Link>
          <button
            type="button"
            onClick={() => setSearchOpen(true)}
            className="rounded border border-stone-300 px-2 py-1 muted hover:border-stone-400 dark:border-stone-700"
          >
            Search ⌘K
          </button>
        </nav>
      </header>

      <div className="flex min-h-0 flex-1">
        <Sidebar indexing={indexing} />
        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <Routes>
            <Route path="/" element={<WelcomeRoute />} />
            <Route path="/stats" element={<StatsRoute />} />
            <Route path="/s/:provider/:id" element={<SessionRoute />} />
          </Routes>
        </main>
      </div>

      <SearchDialog open={searchOpen} onClose={() => setSearchOpen(false)} />
    </div>
  );
}
