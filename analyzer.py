import os
import requests
import streamlit as st

def get_api_key():
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    return os.getenv("GEMINI_API_KEY")

def analyze_market_with_gemini(breadth_score, ema20, ema50, ema200, df_assets, data_quality="Alta"):
    api_key = get_api_key()
    
    if not api_key:
        return "⚠️ **No se ha configurado la API Key de Gemini.**"
    
    # Instrucción de sistema oficial (no se imprime en pantalla)
    system_prompt = (
        "Eres un estratega cuantitativo senior en criptomonedas. "
        "Tu única tarea es generar informes tácticos ejecutivos directamente en español, "
        "sin preámbulos, sin notas de verificación ni texto en otros idiomas."
    )

    # Datos cuantitativos limpios
    user_prompt = f"""
Analiza estos datos cuantitativos de amplitud de mercado y redacta el informe en español:

DATOS TÉCNICOS:
- Breadth Score: {breadth_score:.1f}/100
- Porcentaje sobre EMA 20 (Corto plazo): {ema20:.1f}%
- Porcentaje sobre EMA 50 (Medio plazo): {ema50:.1f}%
- Porcentaje sobre EMA 200 (Largo plazo / Macro): {ema200:.1f}%

ESTRUCTURA DEL INFORME:

### 🧭 1. Régimen de Mercado & Diagnóstico
* **Régimen:** [Pánico / Capitulación, Acumulación, Expansión o Rebote Técnico Frágil]
* **Diagnóstico Cuantitativo:** [Evaluación directa de la salud interna del mercado]

### ⚠️ 2. Divergencias y Estructura
* **Comportamiento de EMAs:** [Contraste entre EMA 20 y EMA 200]
* **Riesgo Estructural:** [Evaluación de riesgo y sostenibilidad de precios]

### 🎯 3. Plan de Acción Táctico
* **Estrategia Spot:** [Gestión de liquidez y compras]
* **Estrategia Futuros / Apalancamiento:** [Sesgo y gestión de exposición]
* **Veredicto:** [Conclusión final concisa]
"""

    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [
            {"parts": [{"text": user_prompt}]}
        ],
        "generationConfig": {
            "temperature": 0.1
        }
    }

    try:
        list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        res_list = requests.get(list_url, timeout=10)
        list_data = res_list.json()

        if "error" in list_data:
            return f"⚠️ Error de autenticación Google: {list_data['error'].get('message', 'Clave no válida')}"

        all_models = [
            m["name"] for m in list_data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
        
        deprecated_tags = ["2.5-flash", "gemini-pro"]
        valid_models = [m for m in all_models if not any(dep in m for dep in deprecated_tags)]

        if not valid_models:
            valid_models = all_models

        last_error = ""

        for model_path in valid_models:
            generate_url = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:generateContent?key={api_key}"
            res = requests.post(generate_url, json=payload, timeout=30)
            data = res.json()

            if "candidates" in data and len(data["candidates"]) > 0:
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                # Limpieza de seguridad por si quedara algún bloque previo
                if "### 🧭 1." in raw_text:
                    raw_text = "### 🧭 1." + raw_text.split("### 🧭 1.", 1)[1]
                return raw_text
            elif "error" in data:
                last_error = data["error"].get("message", "Error desconocido")
                continue

        return f"⚠️ No se pudo generar con los modelos activos: {last_error}"

    except Exception as e:
        return f"⚠️ Error de conexión con Gemini: {str(e)}"
