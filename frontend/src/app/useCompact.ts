import { useEffect, useState } from "react";
export function useCompact() {
  const [compact, setCompact] = useState(() => window.matchMedia("(max-width: 1100px)").matches);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 1100px)");
    const update = () => setCompact(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return compact;
}
