import { useState } from "react";
import type { Artist } from "../api/types";
import { hueFor, initials } from "../lib/format";
import { mediaSrc } from "../lib/urls";
import { cx } from "./ui";

interface ArtistImageProps {
  artist: Pick<Artist, "name" | "images">;
  variant?: "thumb" | "tile" | "hero";
  className?: string;
  rounded?: boolean;
}

/** Locally cached artist image with a generated gradient fallback. */
export function ArtistImage({ artist, variant = "tile", className, rounded }: ArtistImageProps) {
  const src = mediaSrc(artist.images?.[variant] ?? artist.images?.tile ?? artist.images?.thumb);
  const [failed, setFailed] = useState<string | null>(null);
  const hue = hueFor(artist.name);
  if (src && failed !== src) {
    return (
      <img
        className={cx("artist-img", rounded && "is-rounded", className)}
        src={src}
        alt=""
        loading="lazy"
        decoding="async"
        draggable={false}
        onError={() => setFailed(src)}
      />
    );
  }
  return (
    <span
      className={cx("artist-img", "artist-img-fallback", rounded && "is-rounded", className)}
      style={{
        background: `radial-gradient(circle at 30% 20%, hsl(${(hue + 30) % 360} 80% 62%), transparent 60%), linear-gradient(135deg, hsl(${hue} 70% 42%), hsl(${(hue + 60) % 360} 65% 28%))`,
      }}
      aria-hidden
    >
      <span className="artist-img-initials">{initials(artist.name)}</span>
    </span>
  );
}
