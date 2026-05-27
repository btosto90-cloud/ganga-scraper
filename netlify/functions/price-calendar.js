// Flight Hunter — Calendario de precios por ruta
// ---------------------------------------------------------------------------
// Samplea N fechas (sábados por defecto) sobre N meses y trae el precio real
// de Google Flights vía SerpApi en paralelo. CDN cache 48h por combinación
// origen+destino+duración+samples — repeticiones idénticas son gratis.
//
// Guardarraíles:
//   - Hard cap por request: 16 fechas. Si llaman con más, se trunca.
//   - SerpApi key del lado server (process.env.SERPAPI_KEY).
//   - Falla parcial es OK: devolvemos las que funcionaron + lista de errores.
//   - No cuenta llamadas idénticas dentro de 48h (CDN edge cache).
// ---------------------------------------------------------------------------

const MAX_SAMPLES_HARD = 16;
const MIN_TRIP_DAYS = 3;
const MAX_TRIP_DAYS = 30;
const MAX_HORIZON_DAYS = 130;   // ~4.3 meses

exports.handler = async (event) => {
  const q = event.queryStringParameters || {};
  const origin = (q.origin || "").trim().toUpperCase();
  const destination = (q.destination || "").trim().toUpperCase();
  const monthsAhead = clamp(parseInt(q.months_ahead || "4"), 1, 4);
  const tripDays = clamp(parseInt(q.trip_days || "14"), MIN_TRIP_DAYS, MAX_TRIP_DAYS);
  const samples = clamp(parseInt(q.samples || "12"), 4, MAX_SAMPLES_HARD);

  if (!origin || !destination) return resp(400, { error: "Faltan origin y destination" });
  if (origin === destination) return resp(400, { error: "Origen y destino son iguales" });

  const KEY = process.env.SERPAPI_KEY;
  if (!KEY) return resp(500, { error: "SERPAPI_KEY no configurada en Netlify" });

  // Generar fechas sample: días sábado distribuidos en el horizonte.
  const horizonDays = Math.min(MAX_HORIZON_DAYS, monthsAhead * 30);
  const stepDays = Math.max(7, Math.floor(horizonDays / samples));
  const today = new Date();
  const dates = [];
  for (let i = 1; i <= samples; i++) {
    const dep = new Date(today);
    dep.setDate(dep.getDate() + i * stepDays);
    // Empujar al sábado más cercano (típicamente más barato y consistente)
    const diff = (6 - dep.getDay() + 7) % 7;
    dep.setDate(dep.getDate() + diff);
    const ret = new Date(dep);
    ret.setDate(ret.getDate() + tripDays);
    dates.push({ dep: iso(dep), ret: iso(ret) });
  }

  // Dedup por (dep,ret) por si el step coincide.
  const seen = new Set();
  const uniqueDates = dates.filter(d => {
    const k = d.dep + d.ret;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });

  // Fetch en paralelo. Errores individuales no rompen el batch.
  const samplesResult = await Promise.all(uniqueDates.map(d => fetchSample(origin, destination, d, KEY)));

  const ok = samplesResult.filter(s => Number.isFinite(s.price_usd));
  const cheapest = ok.length
    ? ok.reduce((m, s) => (s.price_usd < m.price_usd ? s : m))
    : null;

  // Histórico/típico — todos los samples comparten el price_insights de la ruta;
  // tomamos el primero que tenga datos.
  const insights = ok.find(s => s.typical_low) || {};

  return {
    statusCode: 200,
    headers: {
      "Content-Type": "application/json",
      // CDN cache 48h por mismo querystring → re-pedidos idénticos = free.
      // Navegador revalida cada vez (no cachea localmente).
      "Cache-Control": "public, s-maxage=172800, stale-while-revalidate=86400, max-age=0, must-revalidate",
      "Netlify-Vary": "query",
    },
    body: JSON.stringify({
      route: `${origin}-${destination}`,
      origin,
      destination,
      trip_days: tripDays,
      months_ahead: monthsAhead,
      requested: uniqueDates.length,
      ok_count: ok.length,
      failed_count: samplesResult.length - ok.length,
      typical_low: insights.typical_low || null,
      typical_high: insights.typical_high || null,
      cheapest,
      samples: samplesResult,
      generated_at: new Date().toISOString(),
    }),
  };
};

// ---------------------------------------------------------------------------
async function fetchSample(origin, destination, { dep, ret }, KEY) {
  const params = new URLSearchParams({
    engine: "google_flights",
    departure_id: origin,
    arrival_id: destination,
    outbound_date: dep,
    return_date: ret,
    currency: "USD",
    hl: "es",
    gl: "ar",
    type: "1",
    api_key: KEY,
  });
  try {
    const r = await fetch(`https://serpapi.com/search.json?${params}`);
    if (!r.ok) return { dep, ret, error: `HTTP ${r.status}` };
    const data = await r.json();
    if (data.error) return { dep, ret, error: String(data.error).slice(0, 80) };

    const all = (data.best_flights || []).concat(data.other_flights || []);
    const priced = all.filter(o => Number.isFinite(o.price));
    if (!priced.length) return { dep, ret, empty: true };

    const cheap = priced.reduce((m, o) => (o.price < m.price ? o : m));
    const insights = data.price_insights || {};
    const legs = cheap.flights || [];
    return {
      dep,
      ret,
      price_usd: cheap.price,
      airline: legs[0]?.airline || null,
      stops: Math.max(0, legs.length - 1),
      duration_min: cheap.total_duration || null,
      price_level: insights.price_level || null,
      typical_low: (insights.typical_price_range || [])[0] || null,
      typical_high: (insights.typical_price_range || [])[1] || null,
      google_flights_url: data.search_metadata?.google_flights_url || null,
    };
  } catch (e) {
    return { dep, ret, error: String(e).slice(0, 80) };
  }
}

// ---------------------------------------------------------------------------
function clamp(n, lo, hi) { return Math.max(lo, Math.min(hi, Number.isFinite(n) ? n : lo)); }
function iso(d) { return d.toISOString().slice(0, 10); }
function resp(status, obj) {
  return {
    statusCode: status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-cache" },
    body: JSON.stringify(obj),
  };
}
