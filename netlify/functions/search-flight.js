// Proxy serverless a SerpApi / Google Flights.
// El navegador NUNCA ve la API key — se queda como env var del lado servidor.
// URL pública: /.netlify/functions/search-flight?origin=EZE&destination=MAD&outbound_date=2026-09-26&return_date=2026-10-16
// Cada llamada = 1 search del cupo SerpApi (1.000/mes en plan Starter).

exports.handler = async (event) => {
  const q = event.queryStringParameters || {};
  const { origin, destination, outbound_date, return_date } = q;

  if (!origin || !destination || !outbound_date) {
    return resp(400, { error: "Faltan parámetros: origin, destination, outbound_date" });
  }
  if (origin === destination) {
    return resp(400, { error: "Origen y destino no pueden ser iguales" });
  }
  const KEY = process.env.SERPAPI_KEY;
  if (!KEY) return resp(500, { error: "SERPAPI_KEY no configurada en Netlify" });

  const params = new URLSearchParams({
    engine: "google_flights",
    departure_id: origin,
    arrival_id: destination,
    outbound_date,
    currency: "USD",
    hl: "es",
    gl: "ar",
    type: return_date ? "1" : "2",
    api_key: KEY,
  });
  if (return_date) params.set("return_date", return_date);

  let data;
  try {
    const r = await fetch(`https://serpapi.com/search.json?${params}`);
    const text = await r.text();
    try { data = JSON.parse(text); }
    catch { return resp(r.status, { error: "Respuesta inválida de SerpApi", detail: text.slice(0, 200) }); }
    if (!r.ok && !data.error) {
      return resp(r.status, { error: "SerpApi error HTTP " + r.status });
    }
  } catch (e) {
    return resp(502, { error: "Error de red al llamar SerpApi", detail: String(e).slice(0, 200) });
  }
  if (data.error) return resp(400, { error: String(data.error).slice(0, 200) });

  const all = (data.best_flights || []).concat(data.other_flights || []);
  const insights = data.price_insights || {};
  if (!all.length && !insights.lowest_price) {
    return resp(200, { empty: true, message: "Sin opciones para esas fechas" });
  }
  const sorted = all
    .filter(f => Number.isFinite(f.price))
    .sort((a, b) => a.price - b.price)
    .slice(0, 6);

  const lowCostAirlines = new Set([
    "JetSMART", "Flybondi", "Norwegian", "Level", "LEVEL", "Sky Airline",
    "Wizz Air", "Ryanair", "EasyJet", "Vueling", "Arajet", "GOL",
  ]);

  return resp(200, {
    route: `${origin}-${destination}`,
    outbound_date,
    return_date: return_date || null,
    real_price_usd: sorted[0]?.price ?? insights.lowest_price ?? null,
    price_level: insights.price_level || null,
    typical_low: (insights.typical_price_range || [])[0] ?? null,
    typical_high: (insights.typical_price_range || [])[1] ?? null,
    options: sorted.map(o => {
      const airline = o.flights?.[0]?.airline || "?";
      return {
        price: o.price,
        airline,
        is_low_cost: lowCostAirlines.has(airline),
        stops: Math.max(0, (o.flights?.length || 1) - 1),
        duration_min: o.total_duration || null,
      };
    }),
    google_flights_url: data.search_metadata?.google_flights_url || null,
  });
};

function resp(status, obj) {
  return {
    statusCode: status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-cache",
      "Access-Control-Allow-Origin": "*",
    },
    body: JSON.stringify(obj),
  };
}
