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

def analyze_market_with_gemini(breadth_score, ema20, ema50, ema200, df_assets):
    api_key = get_api_key()
    
    if not api_key:
        return """
        ⚠️ **No se ha configurado la API Key de Gemini.**
        
        Configura tu clave en **Settings > Secrets** de Streamlit Cloud:
        ```toml
        GEMINI_API_KEY = "tu_clave"
        ```
        """
    
    prompt = f"""
    Actúa como un estratega cuantitativo senior de criptomonedas. Analiza los siguientes datos de amplitud de mercado:
    - Breadth Score: {breadth_score:.1f}/100
    - Activos > EMA 20: {ema20:.1f}%
    - Activos > EMA 50: {ema50:.1f}%
    - Activos > EMA 200: {ema200:.1f}%
    
    Genera un informe táctico conciso con:
    1. **Régimen de Mercado Actual**: Diagnóstico en una frase (Expansión sana, Divergencia bajista oculta, Rebote técnico o Pánico).
    2. **Riesgo / Oportunidad**: Explicación breve de la salud interna del mercado frente al precio.
    3. **Plan de Acción Táctico**: Directrices para spot y apalancamiento.
    
    Usa formato Markdown limpio y profesional con viñetas.
    """

    try:
        # 1. Obtener lista de modelos disponibles para tu clave
        list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        res_list = requests.get(list_url, timeout=10)
        list_data = res_list.json()

        if "error" in list_data:
            return f"⚠️ Error de autenticación Google: {list_data['error'].get('message', 'Clave no válida')}"

        # 2. Filtrar modelos compatibles y descartar los deprecados
        all_models = [
            m["name"] for m in list_data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
        
        # Descartamos modelos que Google marca como no disponibles
        deprecated_tags = ["2.5-flash", "gemini-pro"]
        valid_models = [m for m in all_models if not any(dep in m for dep in deprecated_tags)]

        if not valid_models:
            valid_models = all_models

        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ]
        }

        last_error = ""

        # 3. Intentar generar con los modelos activos
        for model_path in valid_models:
            generate_url = f"https://generativelanguage.googleapis.com/v1beta/{model_path}:generateContent?key={api_key}"
            res = requests.post(generate_url, json=payload, timeout=20)
            data = res.json()

            if "candidates" in data and len(data["candidates"]) > 0:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            elif "error" in data:
                last_error = data["error"].get("message", "Error desconocido")
                continue

        return f"⚠️ No se pudo generar con los modelos activos. Último error: {last_error}"

    except Exception as e:
        return f"⚠️ Error de conexión con Gemini: {str(e)}"
