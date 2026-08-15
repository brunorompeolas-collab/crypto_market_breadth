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
        # 1. Consultar a Google la lista exacta de modelos disponibles para tu cuenta
        list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        res_list = requests.get(list_url, timeout=10)
        list_data = res_list.json()

        if "error" in list_data:
            return f"⚠️ Error de autenticación Google: {list_data['error'].get('message', 'Clave no válida')}"

        available_models = [
            m["name"] for m in list_data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]

        if not available_models:
            return "⚠️ Tu clave de API no tiene modelos de generación de texto asignados en este momento."

        # 2. Elegir el mejor modelo disponible de la lista devuelta por Google
        # Prioriza flash o 2.0 si existen, de lo contrario toma el primero disponible
        selected_model = None
        for preferred in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini"]:
            for m in available_models:
                if preferred in m:
                    selected_model = m
                    break
            if selected_model:
                break
        
        if not selected_model:
            selected_model = available_models[0]

        # 3. Ejecutar la llamada con el modelo que sabemos con 100% de certeza que existe
        generate_url = f"https://generativelanguage.googleapis.com/v1beta/{selected_model}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ]
        }
        
        res = requests.post(generate_url, json=payload, timeout=20)
        data = res.json()

        if "error" in data:
            return f"⚠️ Error generando contenido con {selected_model}: {data['error'].get('message')}"

        return data["candidates"][0]["content"]["parts"][0]["text"]

    except Exception as e:
        return f"⚠️ Error de conexión con Gemini: {str(e)}"
