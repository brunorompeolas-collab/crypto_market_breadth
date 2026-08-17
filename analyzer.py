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

def generate_rule_based_report(metrics_json: Dict[str, Any], note: str = "") -> str:
    """Generates a structured quantitative report including hidden divergence detection."""
    score = metrics_json.get("market_breadth_score", 50.0)
    ema20 = metrics_json.get("pct_above_ema20", 50.0)
    ema50 = metrics_json.get("pct_above_ema50", 50.0)
    ema200 = metrics_json.get("pct_above_ema200", 50.0)
    tf = metrics_json.get("timeframe", "1d")
    
    recent_trend = get_recent_snapshots_trend(timeframe=tf, limit=7)
    
    if score >= 80:
        regimen = "SOBRECOMPRA EXTREMA / EUFORIA"
        desc = "La gran mayoría de los activos cotizan por encima de sus medias móviles clave."
    elif score >= 60:
        regimen = "SALUD ALCISTA / IMPULSO FAVORABLE"
        desc = "El mercado muestra una amplitud saludable con fuerte participación de la demanda."
    elif score >= 40:
        regimen = "RÉGIMEN NEUTRO / CONSOLIDACIÓN"
        desc = "Equilibrio entre oferta y demanda sin un sesgo direccional macro claro."
    elif score >= 20:
        regimen = "DEBILIDAD ESTRUCTURAL / DISTRIBUCIÓN"
        desc = "Predominio de la presión vendedora en la mayoría de activos del mercado."
    else:
        regimen = "SOBREVENTA EXTREMA / CAPITULACIÓN"
        desc = "Amplitud comprimida en mínimos; potenciales oportunidades para rebotes tácticos."

    div_type = "🟢 **Alineación Saludable**"
    div_desc = "El precio y la amplitud se desplazan en sintonía."
    
    if len(recent_trend) >= 2:
        first_btc = recent_trend[0]['btc_price']
        last_btc = recent_trend[-1]['btc_price']
        first_score = recent_trend[0]['breadth_score']
        last_score = recent_trend[-1]['breadth_score']
        
        btc_change_pct = ((last_btc - first_btc) / first_btc) * 100
        score_change = last_score - first_score
        
        if btc_change_pct <= 0.5 and score_change >= 5.0:
            div_type = "🚀 **Divergencia Alcista Oculta**"
            div_desc = f"El precio de Bitcoin retrocedió o lateralizó ({btc_change_pct:+.1f}%), pero la amplitud mejoró (+{score_change:.1f} pts). Indica acumulación silenciosa."
        elif btc_change_pct >= 0.5 and score_change <= -5.0:
            div_type = "⚠️ **Divergencia Bajista Oculta**"
            div_desc = f"El precio de Bitcoin subió ({btc_change_pct:+.1f}%), pero la amplitud se deterioró ({score_change:.1f} pts). Indica falta de liquidez."

    header = f"{note}\n\n" if note else ""

    return f"""{header}### 📊 Diagnóstico del Régimen de Mercado
**Régimen Identificado:** {regimen}
**Market Breadth Score:** {score}/100

*Descripción:* {desc}

### 🔮 Detección de Divergencias Ocultas
**Clasificación:** {div_type}
*Diagnóstico:* {div_desc}

### 🔍 Análisis Estructural por Temporalidad
- **Corto Plazo (% > EMA20 = {ema20}%):** {"Impulso alcista dinámico" if ema20 >= 50 else "Presión bajista de corto plazo"}.
- **Mediano Plazo (% > EMA50 = {ema50}%):** {"Estructura intermedia sólida" if ema50 >= 50 else "Deterioro de la tendencia intermedia"}.
- **Largo Plazo (% > EMA200 = {ema200}%):** {"Macro-ciclo alcista intacto" if ema200 >= 50 else "Macro-ciclo en terreno de corrección"}.

### 🛡️ Recomendaciones Tácticas y Gestión de Riesgo
- Mantener estricto control de riesgo y apalancamiento conservador.
- Colocar órdenes de Stop Loss adaptadas a la volatilidad de cada par.
"""

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

def analyze_market_with_gemini(breadth_score, ema20_pct, ema50_pct, ema200_pct, df_assets, api_key: Optional[str] = None) -> str:
    key_to_use = api_key or os.getenv("GEMINI_API_KEY")
    
    tf = "1d" # default for now
    metrics_json = {
        "market_breadth_score": breadth_score,
        "pct_above_ema20": ema20_pct,
        "pct_above_ema50": ema50_pct,
        "pct_above_ema200": ema200_pct,
        "timeframe": tf
    }
    
    placeholders = ["your_gemini_api_key_here", "tu_clave_aqui", "your_api_key_here", "xxx"]
    if not key_to_use or key_to_use.strip() == "" or key_to_use.strip().lower() in placeholders:
        return generate_rule_based_report(
            metrics_json, 
            note="ℹ️ **Modo Análisis Cuantitativo:** Mostrando informe basado en algoritmos de amplitud. Configura una `GEMINI_API_KEY` válida para activar el motor de IA."
        )
        
    key_to_use = key_to_use.strip()
    
    recent_trend = get_recent_snapshots_trend(timeframe=tf, limit=7)
    
    summary_payload = {
        "timeframe": tf,
        "market_breadth_score": breadth_score,
        "pct_above_ema20": ema20_pct,
        "pct_above_ema50": ema50_pct,
        "pct_above_ema200": ema200_pct,
        "last_7_snapshots_series": recent_trend,
        "sample_assets": []
    }
    
    if not df_assets.empty:
        assets_sample = df_assets.head(15).to_dict(orient='records')
        summary_payload["sample_assets"] = [
            {
                "symbol": asset["symbol"],
                "price": asset["price"],
                "change_24h": f"{asset.get('change_24h', 0):.2f}%",
                ">EMA20": asset.get("above_ema20", False),
                ">EMA50": asset.get("above_ema50", False),
                ">EMA200": asset.get("above_ema200", False)
            } for asset in assets_sample
        ]

    prompt_text = f"""Analiza los siguientes datos actualizados de Market Breadth y la serie temporal histórica de las últimas 7 capturas:

```json
{json.dumps(summary_payload, indent=2)}
```

Proporciona un informe ejecutivo profesional estructurado rigurosamente con el siguiente formato Markdown:

---
### 📊 Diagnóstico del Régimen de Mercado
Identifica de forma contundente y clara cuál es el régimen actual (Acumulación, Distribución, Sobrecompra Extrema, Sobreventa Extrema).
Explica brevemente la razón principal basada en el Market Breadth Score ({summary_payload['market_breadth_score']}/100).

### 🔮 Detección de Divergencias Ocultas
Clasifica explícitamente la estructura (Divergencia Alcista, Divergencia Bajista, Alineación Saludable).
Justifica detalladamente analizando la serie de las 7 capturas históricas proporcionadas.

### 🔍 Análisis Estructural por Temporalidad
- Corto Plazo (% > EMA20): Evaluación del momentum inmediato.
- Mediano Plazo (% > EMA50): Estabilidad del impulso.
- Largo Plazo (% > EMA200): Salud estructural del ciclo global.

### 🛡️ Recomendaciones Tácticas y Gestión de Riesgo
Instrucciones claras para operadores (gestión de riesgo, stop loss, apalancamiento).
---"""

    model_id = get_best_model(key_to_use)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={key_to_use}"
    
    payload = {
        "systemInstruction": {
            "parts": [
                {
                    "text": "Eres un Analista Cuantitativo y Estratega de Mercados Senior. Responde estrictamente 100% en ESPAÑOL. No incluyas saludos, despedidas, preámbulos ni autochequeos en inglés. Usa Markdown directo con la estructura solicitada."
                }
            ]
        },
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt_text
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2
        }
    }
    
    try:
        resp = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if "candidates" in data and len(data["candidates"]) > 0:
                content = data["candidates"][0]["content"]["parts"][0]["text"]
                return content
        else:
            logging.error(f"Gemini API error: {resp.status_code} - {resp.text}")
            if resp.status_code == 400 and "API_KEY_INVALID" in resp.text:
                note_msg = "⚠️ **Clave API de Gemini No Válida:** La clave configurada fue rechazada. Renueva tu clave en Google AI Studio."
            else:
                note_msg = f"ℹ️ **Informe Alternativo:** Error al conectar con Gemini AI ({resp.status_code})."
            return generate_rule_based_report(metrics_json, note=note_msg)
    except Exception as e:
        logging.error(f"Gemini Request failed: {e}")
        return generate_rule_based_report(metrics_json, note="ℹ️ **Informe Alternativo:** Fallo de red al conectar con Gemini AI.")
