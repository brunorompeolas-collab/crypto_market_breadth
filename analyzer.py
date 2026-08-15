import os
import streamlit as st

def get_api_key():
    # Prioridad: Streamlit Secrets y luego variables de entorno (.env)
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
        
        Añade tu clave en **Settings > Secrets** de Streamlit Cloud como:
        ```toml
        GEMINI_API_KEY = "tu_clave"
        ```
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
        
        Usa formato Markdown limpio y profesional con viñetas.
        """
        
        # Lista de modelos en orden de preferencia
        models_to_try = ['gemini-2.0-flash', 'gemini-1.5-flash-latest', 'gemini-1.5-pro']
        
        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                if response and response.text:
                    return response.text
            except Exception:
                continue
                
        return "⚠️ No se pudo obtener respuesta con los modelos disponibles. Verifica que la API Key tenga los permisos activos."

    except Exception as e:
        return f"⚠️ Error al conectar con Gemini: {str(e)}"
