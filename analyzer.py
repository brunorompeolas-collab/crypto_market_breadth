import os
import streamlit as st

def get_api_key():
    # Intenta leer primero de Streamlit Secrets (Cloud) y luego de variables de entorno (.env local)
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    return os.getenv("GEMINI_API_KEY")

def analyze_market_with_gemini(breadth_score, ema20, ema50, ema200, df_assets):
    api_key = get_api_key()
    
    if not api_key or "tu_clave" in api_key:
        return """
        ⚠️ **No se ha configurado la API Key de Gemini.**
        
        Para activar el análisis inteligente:
        1. Ve a [Google AI Studio](https://aistudio.google.com/app/apikey) y crea una clave gratuita (`AIzaSy...`).
        2. Añádela en los **Settings > Secrets** de Streamlit Cloud como `GEMINI_API_KEY = "tu_clave"`.
        """
    
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        
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
        
        Usa formato Markdown profesional y limpio, con viñetas claras.
        """
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text
    except Exception as e:
        return f"⚠️ Error al conectar con Gemini: {str(e)}"
