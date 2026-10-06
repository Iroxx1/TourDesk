// Hosts the open flyout (start, search, notifications, quick settings, artist overflow).
import { useEffect } from "react";
import { useArtists } from "../api/hooks";
import { ArtistImage } from "../components/ArtistImage";
import { useUi } from "../state/ui";
import { openArtist } from "../state/windows";
import { NotificationCenter } from "./NotificationCenter";
import { QuickSettings } from "./QuickSettings";
import { SearchFlyout } from "./SearchFlyout";
import { StartMenu } from "./StartMenu";
import { sortedArtists } from "./Taskbar";

function ArtistsFlyout() {
  const { data } = useArtists();
  const close = () => useUi.getState().setFlyout(null);
  return (
    <div className="flyout artists-flyout" role="dialog" aria-label="Alle Künstler">
      <h2>Alle Künstler</h2>
      <div className="artists-flyout-grid">
        {sortedArtists(data).map((a) => (
          <button
            key={a.id}
            type="button"
            className="artists-flyout-item"
            onClick={() => {
              openArtist(a.id, a.name, a.images.thumb);
              close();
            }}
          >
            <ArtistImage artist={a} variant="thumb" className="artists-flyout-img" />
            <span>{a.name}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function Flyouts() {
  const flyout = useUi((s) => s.flyout);
  const setFlyout = useUi((s) => s.setFlyout);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        useUi.getState().openSearch();
      } else if (e.key === "Escape" && useUi.getState().flyout && !useUi.getState().confirmRequest) {
        setFlyout(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setFlyout]);

  useEffect(() => {
    if (!flyout) return;
    const onDown = (e: PointerEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target) return;
      if (target.closest(".flyout") || target.closest("[data-flyout-toggle]") || target.closest(".dialog-backdrop")) return;
      setFlyout(null);
    };
    document.addEventListener("pointerdown", onDown, true);
    return () => document.removeEventListener("pointerdown", onDown, true);
  }, [flyout, setFlyout]);

  if (!flyout) return null;
  return (
    <div className="flyout-layer">
      {flyout === "start" && <StartMenu />}
      {flyout === "search" && <SearchFlyout />}
      {flyout === "notifications" && <NotificationCenter />}
      {flyout === "quick" && <QuickSettings />}
      {flyout === "artists" && <ArtistsFlyout />}
    </div>
  );
}
