// Großer Katalog-Knopf neben der Künstlersuche: gezeichnetes Buch, dessen Deckel sich beim Überfahren öffnet.
import { useRef } from "react";

export function BookIcon() {
  return (
    <span className="cat-bookicon" aria-hidden>
      <span className="cat-bookicon-back" />
      <span className="cat-bookicon-pages" />
      <span className="cat-bookicon-cover">
        <span className="cat-bookicon-label">A–Z</span>
      </span>
      <span className="cat-bookicon-ribbon" />
    </span>
  );
}

export function CatalogLaunch({ onOpen }: { onOpen(rect: DOMRect): void }) {
  const ref = useRef<HTMLButtonElement>(null);
  return (
    <button
      ref={ref}
      type="button"
      className="cat-launch"
      onClick={() => onOpen((ref.current?.querySelector(".cat-bookicon") ?? ref.current)!.getBoundingClientRect())}
      aria-haspopup="dialog"
    >
      <BookIcon />
      <span className="cat-launch-text">
        <strong>Katalog</strong>
        <small>Stöbern nach Genre und A–Z</small>
      </span>
    </button>
  );
}
