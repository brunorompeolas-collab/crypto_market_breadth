import sys
sys.dont_write_bytecode = True
import os
import json
import logging
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from database import get_recent_snapshots_trend

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

    # Divergence calculation based on 7-snapshot trend
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
            div_desc = f"El precio de Bitcoin retrocedió o lateralizó ({btc_change_pct:+.1f}%), pero la amplitud del mercado mejoró (+{score_change:.1f} pts en Score). Indica acumulación silenciosa."
        elif btc_change_pct >= 0.5 and score_change <= -5.0:
            div_type = "⚠️ **Divergencia Bajista Oculta**"
            div_desc = f"El precio de Bitcoin subió ({btc_change_pct:+.1f}%), pero la amplitud del mercado se deterioró ({score_change:.1f} pts en Score). Indica falta de liquidez y concentración de capital solo en BTC."

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

def analyze_market_breadth(metrics_json: Dict[str, Any], api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Sends Market Breadth metrics and 7-snapshot trend series to Gemini API
    and returns a structured Spanish financial analysis report with divergence scanner.
    """
    key_to_use = api_key or os.getenv("GEMINI_API_KEY")
    tf = metrics_json.get("timeframe", "1d")
    recent_trend = get_recent_snapshots_trend(timeframe=tf, limit=7)
    
    placeholders = ["your_gemini_api_key_here", "tu_clave_aqui", "your_api_key_here", "xxx"]
    if not key_to_use or key_to_use.strip() == "" or key_to_use.strip().lower() in placeholders:
        return {
            "success": False,
            "error": "No GEMINI_API_KEY provided",
            "report": generate_rule_based_report(
                metrics_json, 
                note="ℹ️ **Modo Análisis Cuantitativo:** Mostrando informe basado en algoritmos de amplitud. Configura una `GEMINI_API_KEY` válida en el panel lateral para activar el motor de IA en tiempo real."
            )
        }
        
    key_to_use = key_to_use.strip()

    summary_payload = {
        "timeframe": tf,
        "total_assets_analyzed": metrics_json.get("total_assets_analyzed"),
        "market_breadth_score": metrics_json.get("market_breadth_score"),
        "pct_above_ema20": metrics_json.get("pct_above_ema20"),
        "pct_above_ema50": metrics_json.get("pct_above_ema50"),
        "pct_above_ema200": metrics_json.get("pct_above_ema200"),
        "btc_price": metrics_json.get("btc_price"),
        "last_7_snapshots_series": recent_trend,
        "sample_assets": [
            {
                "symbol": asset["symbol"],
                "price": asset["price"],
                "change_24h": f"{asset['change_24h']:.2f}%",
                ">EMA20": asset["above_ema20"],
                ">EMA50": asset["above_ema50"],
                ">EMA200": asset["above_ema200"]
            }
            for asset in metrics_json.get("assets_detail", [])[:15]
        ]
    }
    
    prompt = f"""
Actúa como un Analista Cuantitativo y Estratega de Mercados Financieros Senior especializado en activos digitales.

Analiza los siguientes datos actualizados de Market Breadth y la serie temporal histórica de las últimas 7 capturas:

```json
{json.dumps(summary_payload, indent=2)}
```

Proporciona un informe ejecutivo profesional en **español** estructurado rigurosamente con el siguiente formato Markdown:

---
### 📊 Diagnóstico del Régimen de Mercado
Identifica de forma contundente y clara cuál es el régimen actual entre:
- **Acumulación**
- **Distribución**
- **Sobrecompra Extrema**
- **Sobreventa Extrema**

Explica brevemente la razón principal basada en el Market Breadth Score ({summary_payload['market_breadth_score']}/100).

### 🔮 Detección de Divergencias Ocultas
Clasifica de forma explícita la estructura entre una de las siguientes opciones:
- 🚀 **Divergencia Alcista** (si el precio de Bitcoin baja o se consolida mientras la amplitud del mercado sube).
- ⚠️ **Divergencia Bajista** (si el precio de Bitcoin sube o hace máximos mientras la amplitud del mercado cae).
- 🟢 **Alineación Saludable** (si la dirección del precio de Bitcoin y la amplitud coinciden).

Justifica detalladamente analizando la serie de las 7 capturas históricas proporcionadas (`last_7_snapshots_series`).

### 🔍 Análisis Estructural por Temporalidad
- **Corto Plazo (% > EMA20 = {summary_payload['pct_above_ema20']}%):** Evaluación del momentum inmediato.
- **Mediano Plazo (% > EMA50 = {summary_payload['pct_above_ema50']}%):** Estabilidad del impulso.
- **Largo Plazo (% > EMA200 = {summary_payload['pct_above_ema200']}%):** Salud estructural del ciclo global.

### 🛡️ Recomendaciones Tácticas y Gestión de Riesgo
Instrucciones claras para operadores (gestión de riesgo, stop loss, apalancamiento).
---
"""

    errors_logged = []
    candidate_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
    is_api_key_invalid = False

    # Method 1: New Google GenAI SDK (google-genai)
    try:
        from google import genai
        client = genai.Client(api_key=key_to_use)
        
        for model_id in candidate_models:
            try:
                logging.info(f"Trying google.genai with model: {model_id}")
                res = client.models.generate_content(
                    model=model_id,
                    contents=prompt
                )
                if res and hasattr(res, 'text') and res.text:
                    return {
                        "success": True,
                        "report": res.text,
                        "model_used": f"google-genai ({model_id})"
                    }
            except Exception as e_gen:
                err_str = str(e_gen)
                logging.warning(f"google.genai model {model_id} failed: {err_str}")
                errors_logged.append(f"{model_id}: {err_str}")
                if "API_KEY_INVALID" in err_str or "API key not valid" in err_str or "400" in err_str:
                    is_api_key_invalid = True
                    break
    except Exception as e_import1:
        logging.info(f"google.genai SDK not available: {e_import1}")

    # Method 2: Google Generative AI SDK (google-generativeai)
    if not is_api_key_invalid:
        try:
            import google.generativeai as genai_std
            genai_std.configure(api_key=key_to_use)
            
            for model_id in candidate_models:
                try:
                    logging.info(f"Trying google.generativeai with model: {model_id}")
                    model_inst = genai_std.GenerativeModel(model_id)
                    res = model_inst.generate_content(prompt)
                    if res and hasattr(res, 'text'):
                        txt = res.text
                        if txt:
                            return {
                                "success": True,
                                "report": txt,
                                "model_used": f"google-generativeai ({model_id})"
                            }
                except Exception as e_std:
                    err_str = str(e_std)
                    logging.warning(f"google.generativeai model {model_id} failed: {err_str}")
                    errors_logged.append(f"{model_id}: {err_str}")
                    if "API_KEY_INVALID" in err_str or "API key not valid" in err_str:
                        is_api_key_invalid = True
                        break
        except Exception as e_import2:
            logging.info(f"google.generativeai SDK not available: {e_import2}")

    note_msg = "⚠️ **Clave API de Gemini No Válida:** La clave configurada en `GEMINI_API_KEY` fue rechazada por Google API (`API_KEY_INVALID`). Por favor renueva tu clave en [Google AI Studio](https://aistudio.google.com/)." if is_api_key_invalid else "ℹ️ **Informe Alternativo:** No se pudo establecer conexión remota con Gemini AI."

    return {
        "success": False,
        "error": errors_logged[-1] if errors_logged else "API Key No Válida",
        "report": generate_rule_based_report(metrics_json, note=note_msg)
    }

if __name__ == "__main__":
    print("Testing Gemini Analyzer with Divergence Scanner...")
    mock_data = {
        "timeframe": "1d",
        "total_assets_analyzed": 50,
        "market_breadth_score": 65.4,
        "pct_above_ema20": 72.0,
        "pct_above_ema50": 64.0,
        "pct_above_ema200": 60.0,
        "btc_price": 64000.0,
        "assets_detail": []
    }
    res = analyze_market_breadth(mock_data)
    print("\n" + "="*50)
    print("INFORME DE DIVERGENCIAS GENERADO:")
    print("="*50)
    print(res["report"])
