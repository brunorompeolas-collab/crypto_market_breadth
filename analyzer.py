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
    
    prompt = f"""
    Eres un estratega cuantitativo senior de criptomonedas. Analiza en ESPAÑOL los siguientes datos reales de amplitud de mercado:

    - Breadth Score Compuesto: {breadth_score:.1f} / 100
    - Activos sobre EMA 20 (Corto plazo): {ema20:.1f}%
    - Activos sobre EMA 50 (Medio plazo): {ema50:.1f}%
    - Activos sobre EMA 200 (Largo plazo / Macro): {ema200:.1f}%
    - Calidad de los datos: {data_quality}

    Redacta un informe táctico conciso con esta estructura exacta (NO uses LaTeX, flechas matemáticas ni código sin renderizar, solo Markdown limpio y viñetas):

    ### 🧭 1. Régimen de Mercado & Diagnóstico
    * **Régimen:** (Define claramente: Pánico/Capitulación, Expansión, Acumulación o Divergencia Bajista).
    * **Diagnóstico Técnico:** Evaluación de la salud interna frente a los precios.

    ### ⚠️ 2. Divergencias y Estructura
    * **Análisis de EMAs:** Comparativa entre la fuerza inmediata (EMA 20) y la tendencia estructural (EMA 200).
    * **Riesgo Estructural:** Señala si estamos ante un rebote de gato muerto o capitulación real.

    ### 🎯 3. Plan de Acción Táctico
    * **Estrategia Spot:** (Pauta clara de gestión de liquidez o entradas DCA).
    * **Estrategia Apalancamiento / Futuros:** (Nivel de riesgo y sesgo recomendado).
    * **Veredicto:** Una conclusión directa y accionable.
    """

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

        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        last_error = ""

        for model_path in valid_models:
            generate_url = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:generateContent?key={api_key}"
            res = requests.post(generate_url, json=payload, timeout=40)
            data = res.json()

            if "candidates" in data and len(data["candidates"]) > 0:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            elif "error" in data:
                last_error = data["error"].get("message", "Error desconocido")
                continue

        return f"⚠️ No se pudo generar con los modelos activos: {last_error}"

    except Exception as e:
        return f"⚠️ Error de conexión con Gemini: {str(e)}"
