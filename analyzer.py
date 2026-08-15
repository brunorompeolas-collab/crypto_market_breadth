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

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [{"text": prompt}]
            }
        ]
    }
    
    try:
        res = requests.post(url, json=payload, timeout=20)
        data = res.json()
        
        if "error" in data:
            return f"⚠️ Error API Google: {data['error'].get('message', 'Error desconocido')}"
            
        return data["candidates"][0]["content"]["parts"][0]["text"]
        
    except Exception as e:
        return f"⚠️ Error en la conexión HTTP con Gemini: {str(e)}"
