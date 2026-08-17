import sys
sys.dont_write_bytecode = True
import os
import json
import logging
import requests
from typing import Dict, Any, Optional
from database import get_recent_snapshots_trend
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def get_best_model(api_key: str) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            models = resp.json().get('models', [])
            valid_models = []
            deprecated = ["gemini-pro", "gemini-2.5-flash"]
            for m in models:
                name = m.get('name', '').replace('models/', '')
                if 'gemini' in name and 'vision' not in name and name not in deprecated:
                    if 'generateContent' in m.get('supportedGenerationMethods', []):
                        valid_models.append(name)
            
            for pref in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]:
                if pref in valid_models:
                    return pref
            if valid_models:
                return valid_models[0]
    except Exception as e:
        logging.warning(f"Failed to fetch models: {e}")
    return "gemini-1.5-flash"

def evaluate_divergence(recent_trend: list, benchmark: str = 'BTC') -> Dict[str, str]:
    """
    P0.11 - Deterministic Divergence Engine.
    Compares 7-period change in benchmark vs 7-period change in breadth.
    """
    if len(recent_trend) < 2:
        return {
            "type": "NEUTRAL / INCONCLUSIVE",
            "desc": "No hay suficientes datos históricos para detectar divergencias.",
            "metrics": ""
        }
        
    first_snap = recent_trend[0]
    last_snap = recent_trend[-1]
    
    # We want the oldest to the newest. The array from DB is already ascending (oldest first) if we use get_recent_snapshots_trend
    # Wait, get_recent_snapshots_trend returns ascending chronological order. 
    # So index 0 is oldest, index -1 is newest.
    
    b_key = 'btc_price' if benchmark == 'BTC' else 'eth_price'
    
    first_price = first_snap.get(b_key, 0.0)
    last_price = last_snap.get(b_key, 0.0)
    first_score = first_snap.get('breadth_score', 0.0)
    last_score = last_snap.get('breadth_score', 0.0)
    
    if first_price == 0.0:
        return {"type": "NEUTRAL", "desc": "Precio base 0", "metrics": ""}
        
    price_change_pct = ((last_price - first_price) / first_price) * 100
    score_change = last_score - first_score
    
    metrics_str = f"{benchmark} 7-period change: {price_change_pct:+.1f}%\nBreadth change: {score_change:+.1f} points"
    
    if price_change_pct <= 0.5 and score_change >= 5.0:
        div_type = "BULLISH BREADTH DIVERGENCE"
        div_desc = f"El precio de {benchmark} retrocedió o lateralizó, pero la amplitud mejoró. Indica acumulación silenciosa."
    elif price_change_pct >= 0.5 and score_change <= -5.0:
        div_type = "BEARISH BREADTH DIVERGENCE"
        div_desc = f"El precio de {benchmark} subió, pero la amplitud se deterioró. Indica debilidad estructural y falta de liquidez."
    elif price_change_pct > 2.0 and score_change > 2.0:
        div_type = "ALIGNED EXPANSION"
        div_desc = f"El precio y la amplitud crecen orgánicamente juntos."
    elif price_change_pct < -2.0 and score_change < -2.0:
        div_type = "ALIGNED DETERIORATION"
        div_desc = f"El precio y la amplitud caen de la mano, confirmando presión vendedora."
    else:
        div_type = "NEUTRAL / INCONCLUSIVE"
        div_desc = "Precio y amplitud no muestran divergencias extremas significativas."
        
    return {
        "type": div_type,
        "desc": div_desc,
        "metrics": metrics_str
    }

def analyze_market_with_gemini(snapshot: Dict[str, Any], df_assets, benchmark: str, api_key: Optional[str] = None) -> str:
    """
    P0.12 - P0.21: Gemini is an interpreter of quantitative signals, not the generator.
    """
    key_to_use = api_key or os.getenv("GEMINI_API_KEY")
    placeholders = ["your_gemini_api_key_here", "tu_clave_aqui", "your_api_key_here", "xxx"]
    if not key_to_use or key_to_use.strip() == "" or key_to_use.strip().lower() in placeholders:
        return "⚠️ **Error:** No se ha detectado una API Key válida de Gemini. Por favor, añádela en la configuración (.env)."
        
    key_to_use = key_to_use.strip()
    
    tf = snapshot.get("timeframe", "1d")
    exchange = snapshot.get("exchange", "binance")
    universe = snapshot.get("universe_version", "BR1")
    
    recent_trend = get_recent_snapshots_trend(timeframe=tf, limit=7, exchange=exchange, universe=universe)
    divergence_data = evaluate_divergence(recent_trend, benchmark=benchmark)
    
    summary_payload = {
        "timeframe": tf,
        "benchmark_selected": benchmark,
        "current_snapshot": snapshot,
        "divergence_analysis": divergence_data,
        "last_7_snapshots_series": recent_trend,
        "sample_assets": []
    }
    
    if not df_assets.empty:
        assets_sample = df_assets.head(15).to_dict(orient='records')
        summary_payload["sample_assets"] = [
            {
                "symbol": asset["symbol"],
                "price": asset["price"],
                ">EMA20": asset.get("above_ema20", False),
                ">EMA50": asset.get("above_ema50", False),
                ">EMA200": asset.get("above_ema200", False)
            } for asset in assets_sample
        ]

    prompt_text = f"""Analiza los datos pre-calculados del sistema cuantitativo de Market Breadth (Amplitud de Mercado):

```json
{json.dumps(summary_payload, indent=2)}
```

Eres un intérprete de los algoritmos del sistema. Tus conclusiones DEBEN basarse en las métricas JSON proporcionadas.
El motor ya ha calculado las divergencias en 'divergence_analysis'. Interpreta y explica esto de manera ejecutiva en español.

Estructura obligatoria (Usa Markdown):
---
### 📊 Diagnóstico del Régimen de Mercado
(Explica el régimen basado en el Breadth Score actual y la calidad de los datos).

### 🔮 Análisis de Divergencias ({benchmark})
(Explica el tipo de divergencia detectada por el sistema: {divergence_data['type']}, y qué implicaciones tiene en base a sus métricas).

### 🔍 Estructura de Medias Móviles
(Interpreta la participación en EMA20, EMA50 y EMA200).

### 🛡️ Recomendaciones Tácticas
(Recomendaciones orientadas a la temporalidad {tf}).
---"""

    model_id = get_best_model(key_to_use)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={key_to_use}"
    
    payload = {
        "systemInstruction": {
            "parts": [
                {
                    "text": "Eres el intérprete de inteligencia artificial del Crypto Breadth Terminal. Tu objetivo es explicar en un lenguaje humano profesional los resultados cuantitativos ya precalculados."
                }
            ]
        },
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {"temperature": 0.2}
    }
    
    try:
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if "candidates" in data and len(data["candidates"]) > 0:
                return data["candidates"][0]["content"]["parts"][0]["text"]
        else:
            logging.error(f"Gemini API error: {resp.status_code} - {resp.text}")
            return f"⚠️ **Error en Gemini:** El modelo devolvió un estado {resp.status_code}."
    except Exception as e:
        logging.error(f"Gemini Request failed: {e}")
        return f"⚠️ **Fallo de Red:** No se pudo conectar a la API de Google Gemini. ({e})"
