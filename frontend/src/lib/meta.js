import { useEffect, useState } from "react";
import { api } from "./api";

/** Vocabulary and bounds. The API (/api/meta) is the source of truth; these defaults match ml/config.py. */
export const DEFAULT_META = {
  categories: ["Tops", "Bottoms", "Dresses", "Footwear", "Outerwear", "Accessories"],
  seasons: ["Winter", "Summer", "Monsoon", "Festive"],
  preferences: ["Casual", "Formal", "Sporty", "Trendy", "Classic"],
  month_to_season: { 1: "Winter", 2: "Winter", 3: "Summer", 4: "Summer", 5: "Summer", 6: "Monsoon", 7: "Monsoon",
    8: "Monsoon", 9: "Monsoon", 10: "Festive", 11: "Festive", 12: "Winter" },
  bounds: { Purchase_Frequency: [1, 500], Recency: [0, 730], Month: [1, 12], Price: [0, 50000], Discount: [0, 90] },
  detectors: ["DDM"],
  detector_info: {},
  simulation_enabled: true,
  max_upload_mb: 5,
};

let cache = null;
let inflight = null;

export function useMeta() {
  const [meta, setMeta] = useState(cache || DEFAULT_META);
  useEffect(() => {
    if (cache) return undefined;
    let alive = true;
    inflight = inflight || api("/api/meta").then((m) => (cache = { ...DEFAULT_META, ...m }));
    inflight.then((m) => alive && setMeta(m)).catch(() => { inflight = null; });
    return () => { alive = false; };
  }, []);
  return meta;
}

export const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];
