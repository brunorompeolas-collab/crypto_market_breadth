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
    Genera un informe táctico de mercado en ESPAÑOL basado en los siguientes datos cuantitativos:
    - Puntuación de Amplitud (Breadth Score): {breadth_score:.1f} sobre 100
    - Activos por encima de EMA 20 (Corto Plazo): {ema20:.1f}%
    - Activos por encima de EMA 50 (Medio Plazo): {ema50:.1f}%
    - Activos por encima de EMA 200 (Largo Plazo / Macro): {ema200:.1f}%

    IMPORTANTE: Escribe TODO el informe únicamente en idioma español. No incluyas texto en inglés, no repitas estas instrucciones y no uses fórmulas LaTeX. Responde directamente con las siguientes 3 secciones en Markdown:

    ### 🧭 1. Régimen de Mercado & Diagnóstico
    * **Régimen:** (Indica uno: Pánico/Capitulación, Expansión Alcista, Acumulación o Rebote Técnico Frágil).
    * **Diagnóstico Cuantitativo:** Explicación directa del estado de salud interna del mercado frente al precio.

    ### ⚠️ 2. Divergencias y Estructura
    * **Comportamiento de EMAs:** Contraste entre el corto plazo (EMA 20) y la estructura macro (EMA 200).
    * **Riesgo Estructural:** Evaluación de si se trata de un rebote falso o de una capitulación con oportunidad.

    ### 🎯 3. Plan de Acción Táctico
    * **Estrategia Spot:** Directrices de liquidez y gestión de compras.
    * **Estrategia Futuros / Apalancamiento:** Nivel de riesgo y sesgo operativo recomendado.
    * **Veredicto:** Conclusión final en una frase clara.
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

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2
            }
        }
        
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
