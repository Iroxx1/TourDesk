import { wallpaperUrl } from "../lib/urls";

export function Wallpaper({ wallpaper }: { wallpaper: string }) {
  return (
    <div className="wallpaper" aria-hidden>
      <div className="wallpaper-image" style={{ backgroundImage: `url("${wallpaperUrl(wallpaper)}")` }} />
      <div className="wallpaper-tint" />
    </div>
  );
}
