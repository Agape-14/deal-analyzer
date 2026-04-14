"use client";

import * as React from "react";
import Map, {
  Layer,
  Marker,
  NavigationControl,
  Popup,
  Source,
  type MapRef,
} from "react-map-gl/maplibre";
import type { StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  Layers,
  Loader2,
  MapPin,
  RefreshCw,
  AlertCircle,
  Utensils,
  ShoppingCart,
  TrainFront,
  GraduationCap,
  Stethoscope,
  Trees,
  Briefcase,
  Building,
  Satellite,
  Map as MapIcon,
  Moon,
} from "lucide-react";
import { toast } from "sonner";
import { motion, AnimatePresence } from "framer-motion";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { cn, fmtDate, fmtMoney } from "@/lib/utils";
import type { LocationBundle, Poi, PoiCategory } from "@/lib/types";

/* ================== Map styles (all free, no API key) ================== */

/** CartoDB Dark Matter — free dark vector tiles that match our theme. */
const DARK_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    "carto-dark": {
      type: "raster",
      tiles: [
        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
        "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution:
        '&copy; <a href="https://carto.com/attributions">CARTO</a> &copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>',
    },
  },
  layers: [{ id: "base", type: "raster", source: "carto-dark" }],
};

/** ESRI World Imagery — free satellite, no API key required. */
const SATELLITE_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    "esri-imagery": {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution:
        "Tiles &copy; Esri &mdash; Source: Esri, Maxar, Earthstar Geographics",
    },
    "carto-labels": {
      type: "raster",
      tiles: [
        "https://a.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}.png",
        "https://b.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
    },
  },
  layers: [
    { id: "imagery", type: "raster", source: "esri-imagery" },
    { id: "labels", type: "raster", source: "carto-labels" },
  ],
};

/** CartoDB Positron — free light style for when you'd rather see streets. */
const STREETS_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    "carto-positron": {
      type: "raster",
      tiles: [
        "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
        "https://b.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution:
        '&copy; <a href="https://carto.com/attributions">CARTO</a> &copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>',
    },
  },
  layers: [{ id: "base", type: "raster", source: "carto-positron" }],
};

type StyleKey = "dark" | "satellite" | "streets";
const STYLES: Record<StyleKey, { label: string; icon: React.ComponentType<{ className?: string }>; spec: StyleSpecification }> = {
  dark: { label: "Dark", icon: Moon, spec: DARK_STYLE },
  satellite: { label: "Satellite", icon: Satellite, spec: SATELLITE_STYLE },
  streets: { label: "Streets", icon: MapIcon, spec: STREETS_STYLE },
};

/* ================== Categories (UI) ================== */

const CAT: Record<PoiCategory, { label: string; icon: React.ComponentType<{ className?: string }>; color: string }> = {
  apartments:  { label: "Apartments",  icon: Building,       color: "hsl(var(--primary))" },
  restaurants: { label: "Restaurants", icon: Utensils,       color: "#ff9f43" },
  grocery:     { label: "Grocery",     icon: ShoppingCart,   color: "#26de81" },
  transit:     { label: "Transit",     icon: TrainFront,     color: "#45aaf2" },
  schools:     { label: "Schools",     icon: GraduationCap,  color: "#a55eea" },
  healthcare:  { label: "Healthcare",  icon: Stethoscope,    color: "#ef5777" },
  parks:       { label: "Parks",       icon: Trees,          color: "#20bf6b" },
  employers:   { label: "Employers",   icon: Briefcase,      color: "#fed330" },
};

const CATEGORY_ORDER: PoiCategory[] = [
  "apartments", "restaurants", "grocery", "transit", "schools", "healthcare", "parks", "employers",
];

const RADII_M = [800, 1609, 3219, 8047]; // 0.5, 1, 2, 5 mi
const MI_LABEL = (m: number) => {
  const mi = m / 1609.34;
  return mi < 1 ? `${mi.toFixed(1)} mi` : `${Math.round(mi)} mi`;
};

/* ============================== Component ============================== */

export function LocationTab({
  dealId,
  initialLat,
  initialLng,
  proformaRent,
  unitMix,
}: {
  dealId: number;
  initialLat: number | null | undefined;
  initialLng: number | null | undefined;
  proformaRent?: number | null;
  unitMix?: string | null;
}) {
  const mapRef = React.useRef<MapRef | null>(null);
  const [styleKey, setStyleKey] = React.useState<StyleKey>("satellite");
  const [radiusM, setRadiusM] = React.useState<number>(1609);
  const [bundle, setBundle] = React.useState<LocationBundle | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [refreshing, setRefreshing] = React.useState(false);
  const [enabled, setEnabled] = React.useState<Set<PoiCategory>>(
    new Set(["apartments", "transit", "grocery"]),
  );
  const [selected, setSelected] = React.useState<Poi | null>(null);

  // Initial fetch
  React.useEffect(() => {
    setLoading(true);
    api
      .get<LocationBundle>(`/api/deals/${dealId}/location?radius_m=${radiusM}`)
      .then((b) => setBundle(b))
      .catch((e) => {
        toast.error("Couldn't load location", {
          description: (e as { detail?: string })?.detail,
        });
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dealId]);

  // Refresh when radius changes (but not on first render)
  const firstRender = React.useRef(true);
  React.useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    void refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [radiusM]);

  async function refetch(force = false) {
    setRefreshing(true);
    try {
      const b = await api.get<LocationBundle>(
        `/api/deals/${dealId}/location?radius_m=${radiusM}${force ? "&refresh=true" : ""}`,
      );
      setBundle(b);
    } catch (e) {
      toast.error("Refresh failed", { description: (e as { detail?: string })?.detail });
    } finally {
      setRefreshing(false);
    }
  }

  const lat = bundle?.lat ?? initialLat ?? null;
  const lng = bundle?.lng ?? initialLng ?? null;
  const hasCoords = typeof lat === "number" && typeof lng === "number";

  const fmr2br = bundle?.fmr?.rents?.br2 ?? null;
  const fmrComparison = React.useMemo(() => {
    if (!fmr2br || !proformaRent || proformaRent <= 0) return null;
    const delta = ((proformaRent - fmr2br) / fmr2br) * 100;
    return { fmr2br, proformaRent, delta };
  }, [fmr2br, proformaRent]);

  function toggleCategory(c: PoiCategory) {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-4 h-[calc(100vh-280px)] min-h-[600px]">
      {/* ============== MAP ============== */}
      <Card elevated className="p-0 overflow-hidden relative">
        {loading && !bundle ? (
          <div className="h-full grid place-items-center text-sm text-muted-foreground">
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading map data…
            </div>
          </div>
        ) : !hasCoords ? (
          <GeocodeFailure bundle={bundle} onManual={() => toast.info("Open the side panel to manually set coordinates")} />
        ) : (
          <>
            <Map
              ref={mapRef}
              initialViewState={{ longitude: lng, latitude: lat, zoom: 14 }}
              mapStyle={STYLES[styleKey].spec}
              attributionControl={true}
              style={{ width: "100%", height: "100%" }}
            >
              <NavigationControl position="top-right" showCompass={false} />

              {/* Radius ring */}
              <Source
                id="radius"
                type="geojson"
                data={circleGeoJson(lat, lng, radiusM)}
              >
                <Layer
                  id="radius-fill"
                  type="fill"
                  paint={{
                    "fill-color": "hsl(200, 100%, 60%)",
                    "fill-opacity": 0.08,
                  }}
                />
                <Layer
                  id="radius-line"
                  type="line"
                  paint={{
                    "line-color": "hsl(200, 100%, 60%)",
                    "line-width": 1.5,
                    "line-dasharray": [3, 2],
                  }}
                />
              </Source>

              {/* Primary property marker */}
              <Marker longitude={lng} latitude={lat} anchor="bottom">
                <div className="relative -translate-y-1 group">
                  <div className="absolute inset-0 bg-primary/30 rounded-full blur-xl animate-pulse" />
                  <div className="relative h-8 w-8 rounded-full bg-primary ring-4 ring-background grid place-items-center shadow-[0_8px_24px_-8px_rgba(0,0,0,.8)]">
                    <MapPin className="h-4 w-4 text-primary-foreground" />
                  </div>
                </div>
              </Marker>

              {/* POI markers */}
              {bundle &&
                CATEGORY_ORDER.filter((c) => enabled.has(c)).flatMap((c) => {
                  const pois = bundle.categories?.[c] ?? [];
                  return pois.map((p) => (
                    <Marker
                      key={p.id}
                      longitude={p.lng}
                      latitude={p.lat}
                      anchor="bottom"
                      onClick={(e) => {
                        e.originalEvent.stopPropagation();
                        setSelected(p);
                      }}
                    >
                      <PoiPin category={c} name={p.name} />
                    </Marker>
                  ));
                })}

              {/* Popup */}
              {selected && (
                <Popup
                  longitude={selected.lng}
                  latitude={selected.lat}
                  anchor="top"
                  onClose={() => setSelected(null)}
                  closeOnClick={false}
                  closeButton={false}
                  maxWidth="300px"
                  className="[&_.maplibregl-popup-content]:!bg-popover [&_.maplibregl-popup-content]:!text-popover-foreground [&_.maplibregl-popup-content]:!p-0 [&_.maplibregl-popup-content]:!rounded-lg [&_.maplibregl-popup-tip]:!border-t-popover"
                >
                  <PoiPopup poi={selected} onClose={() => setSelected(null)} />
                </Popup>
              )}
            </Map>

            {/* Style switcher + radius control overlaid top-left */}
            <div className="absolute top-3 left-3 flex flex-col gap-2">
              <div className="inline-flex rounded-lg border border-border/80 bg-card/90 backdrop-blur-md p-1 shadow-lg">
                {(Object.keys(STYLES) as StyleKey[]).map((k) => {
                  const S = STYLES[k];
                  const active = styleKey === k;
                  return (
                    <button
                      key={k}
                      onClick={() => setStyleKey(k)}
                      className={cn(
                        "inline-flex items-center gap-1.5 px-2.5 h-7 rounded-md text-xs font-medium transition-colors",
                        active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                      )}
                      aria-pressed={active}
                    >
                      <S.icon className="h-3 w-3" />
                      {S.label}
                    </button>
                  );
                })}
              </div>
              <div className="inline-flex rounded-lg border border-border/80 bg-card/90 backdrop-blur-md p-1 shadow-lg">
                {RADII_M.map((m) => (
                  <button
                    key={m}
                    onClick={() => setRadiusM(m)}
                    className={cn(
                      "px-2.5 h-7 rounded-md text-xs font-medium tabular-nums transition-colors",
                      radiusM === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {MI_LABEL(m)}
                  </button>
                ))}
              </div>
            </div>

            {/* Refresh pill top-right */}
            <div className="absolute top-3 right-14">
              <Button size="sm" variant="secondary" onClick={() => refetch(true)} disabled={refreshing}>
                {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                Refresh
              </Button>
            </div>
          </>
        )}
      </Card>

      {/* ============== SIDE PANEL ============== */}
      <div className="flex flex-col gap-4 min-h-0">
        <Card elevated className="p-4">
          <div className="flex items-center gap-2 mb-3">
            <Layers className="h-4 w-4 text-muted-foreground" />
            <h3 className="text-sm font-semibold">Layers</h3>
            <span className="ml-auto text-[10px] uppercase tracking-wider text-muted-foreground">
              {bundle ? totalPois(bundle) : 0} POIs
            </span>
          </div>
          <div className="space-y-1">
            {CATEGORY_ORDER.map((c) => {
              const spec = CAT[c];
              const count = bundle?.categories?.[c]?.length ?? 0;
              const active = enabled.has(c);
              return (
                <button
                  key={c}
                  onClick={() => toggleCategory(c)}
                  className={cn(
                    "w-full flex items-center gap-2.5 px-2 py-1.5 rounded-md text-xs transition-colors",
                    active
                      ? "bg-muted/70 text-foreground ring-1 ring-border/60"
                      : "text-muted-foreground hover:text-foreground hover:bg-muted/40",
                  )}
                >
                  <span
                    className="h-2.5 w-2.5 rounded-full shrink-0"
                    style={{ backgroundColor: spec.color, opacity: active ? 1 : 0.35 }}
                  />
                  <spec.icon className="h-3.5 w-3.5 shrink-0" />
                  <span className="flex-1 text-left font-medium">{spec.label}</span>
                  <span className={cn("tabular-nums text-[10px]", active ? "" : "opacity-60")}>
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
        </Card>

        {/* Rent comparison */}
        <Card elevated className="p-4">
          <h3 className="text-sm font-semibold mb-2">Rent context</h3>
          {fmr2br ? (
            <>
              <div className="text-[11px] text-muted-foreground">
                HUD Fair Market Rent · {bundle?.fmr?.metro ?? bundle?.fmr?.county ?? "zip " + bundle?.fmr?.zip}
                {bundle?.fmr?.year && <> · {bundle.fmr.year}</>}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs tabular-nums">
                <FmrRow label="Studio" value={bundle?.fmr?.rents?.studio} />
                <FmrRow label="1 BR" value={bundle?.fmr?.rents?.br1} />
                <FmrRow label="2 BR" value={bundle?.fmr?.rents?.br2} highlight />
                <FmrRow label="3 BR" value={bundle?.fmr?.rents?.br3} />
              </div>
              {fmrComparison && (
                <div
                  className={cn(
                    "mt-3 p-2.5 rounded-md text-xs ring-1",
                    fmrComparison.delta > 25
                      ? "bg-destructive/10 text-destructive ring-destructive/30"
                      : fmrComparison.delta > 10
                        ? "bg-warning/10 text-warning ring-warning/30"
                        : "bg-success/10 text-success ring-success/30",
                  )}
                >
                  <div className="font-medium">
                    Proforma rent {fmtMoney(proformaRent!)} vs FMR {fmtMoney(fmr2br)}
                  </div>
                  <div className="mt-0.5 text-[10px] opacity-90">
                    {fmrComparison.delta > 0 ? "+" : ""}
                    {fmrComparison.delta.toFixed(1)}%{" "}
                    {fmrComparison.delta > 25
                      ? "above market — aggressive"
                      : fmrComparison.delta > 10
                        ? "above market — verify"
                        : "within market range"}
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="text-xs text-muted-foreground">
              Zip-level rent averages are free from HUD. Set{" "}
              <code className="font-mono bg-muted/60 px-1 py-0.5 rounded text-[10px]">HUD_API_TOKEN</code>{" "}
              (register free at huduser.gov) to enable.
            </div>
          )}
        </Card>

        {bundle?.display_name && (
          <Card elevated className="p-4">
            <div className="text-[10px] uppercase tracking-[0.12em] text-muted-foreground mb-1">
              Resolved location
            </div>
            <div className="text-xs leading-relaxed">{bundle.display_name}</div>
            {bundle.fetched_at && (
              <div className="text-[10px] text-muted-foreground mt-2">
                Updated {fmtDate(new Date(bundle.fetched_at * 1000).toISOString())}
              </div>
            )}
          </Card>
        )}

        <div className="text-[10px] text-muted-foreground leading-relaxed mt-auto">
          Map tiles © CARTO / Esri · POI data © OpenStreetMap contributors. All
          free / unauthenticated sources.
        </div>
      </div>
    </div>
  );
}

/* ============================== Helpers ============================== */

function totalPois(bundle: LocationBundle): number {
  return Object.values(bundle.categories ?? {}).reduce(
    (a, v) => a + (Array.isArray(v) ? v.length : 0),
    0,
  );
}

function circleGeoJson(lat: number, lng: number, radiusM: number) {
  // ~64-segment polygon approximating a circle, in WGS84 lat/lng.
  const pts: number[][] = [];
  const R = 6371000;
  for (let i = 0; i <= 64; i++) {
    const brng = (i / 64) * 2 * Math.PI;
    const latR = (lat * Math.PI) / 180;
    const lngR = (lng * Math.PI) / 180;
    const d = radiusM / R;
    const lat2 = Math.asin(
      Math.sin(latR) * Math.cos(d) + Math.cos(latR) * Math.sin(d) * Math.cos(brng),
    );
    const lng2 =
      lngR +
      Math.atan2(
        Math.sin(brng) * Math.sin(d) * Math.cos(latR),
        Math.cos(d) - Math.sin(latR) * Math.sin(lat2),
      );
    pts.push([(lng2 * 180) / Math.PI, (lat2 * 180) / Math.PI]);
  }
  return {
    type: "Feature",
    properties: {},
    geometry: { type: "Polygon", coordinates: [pts] },
  } as const;
}

function PoiPin({ category, name }: { category: PoiCategory; name: string }) {
  const spec = CAT[category];
  const Icon = spec.icon;
  return (
    <div className="relative group -translate-y-1 cursor-pointer" title={name}>
      <div
        className="h-5 w-5 rounded-full ring-2 ring-background grid place-items-center shadow-md transition-transform group-hover:scale-110"
        style={{ backgroundColor: spec.color }}
      >
        <Icon className="h-2.5 w-2.5 text-black/80" />
      </div>
    </div>
  );
}

function PoiPopup({ poi, onClose }: { poi: Poi; onClose: () => void }) {
  const spec = CAT[poi.category as PoiCategory] ?? CAT.employers;
  const Icon = spec.icon;
  const addr = [
    poi.tags["addr:housenumber"],
    poi.tags["addr:street"],
    poi.tags["addr:city"],
    poi.tags["addr:postcode"],
  ]
    .filter(Boolean)
    .join(" ");
  const flats = poi.tags["building:flats"] || poi.tags["units"];
  const levels = poi.tags["building:levels"];
  const website = poi.tags["website"];
  const phone = poi.tags["phone"];

  return (
    <div className="w-64 overflow-hidden">
      <div className="flex items-center gap-2 px-3.5 pt-3 pb-2 border-b border-border/50">
        <span
          className="h-5 w-5 rounded-full grid place-items-center shrink-0"
          style={{ backgroundColor: spec.color }}
        >
          <Icon className="h-3 w-3 text-black/80" />
        </span>
        <div className="min-w-0">
          <div className="text-sm font-semibold truncate">{poi.name}</div>
          <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
            {spec.label} · {(poi.distance_m / 1609.34).toFixed(2)} mi
          </div>
        </div>
      </div>
      <div className="px-3.5 py-2.5 text-xs space-y-1.5">
        {addr && <div className="text-muted-foreground">{addr}</div>}
        {(flats || levels) && (
          <div className="text-muted-foreground">
            {flats && <>Units: {flats}</>}
            {flats && levels && " · "}
            {levels && <>Levels: {levels}</>}
          </div>
        )}
        {phone && <div className="text-muted-foreground">{phone}</div>}
        {website && (
          <a
            href={website}
            target="_blank"
            rel="noreferrer"
            className="inline-block text-primary hover:underline truncate max-w-full"
          >
            {website.replace(/^https?:\/\//, "")}
          </a>
        )}
      </div>
    </div>
  );
}

function FmrRow({ label, value, highlight }: { label: string; value?: number | null; highlight?: boolean }) {
  return (
    <div
      className={cn(
        "flex justify-between gap-2 px-2 py-1.5 rounded-md",
        highlight && "bg-primary/10 ring-1 ring-primary/20",
      )}
    >
      <span className="text-muted-foreground">{label}</span>
      <span className="font-semibold tabular-nums">{value ? fmtMoney(value) : "—"}</span>
    </div>
  );
}

function GeocodeFailure({
  bundle,
  onManual,
}: {
  bundle: LocationBundle | null;
  onManual: () => void;
}) {
  return (
    <div className="h-full grid place-items-center p-10 text-center">
      <div className="max-w-sm">
        <div className="inline-flex h-11 w-11 rounded-xl bg-warning/10 ring-1 ring-warning/30 grid place-items-center mb-3">
          <AlertCircle className="h-5 w-5 text-warning" />
        </div>
        <h3 className="text-base font-semibold tracking-tight">Couldn&apos;t place this deal on the map</h3>
        <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
          {bundle?.error ||
            "Add a street address, city, and state to the deal — geocoding happens automatically."}
        </p>
        <AnimatePresence>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="text-[11px] text-muted-foreground mt-5"
          >
            Tip: Once you find the exact property on the map, use the &ldquo;Manual
            place&rdquo; picker to pin it. Future refreshes will re-query from that
            point.
          </motion.div>
        </AnimatePresence>
      </div>
    </div>
  );
}
