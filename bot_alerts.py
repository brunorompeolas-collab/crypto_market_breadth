import os
import requests
import logging
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def get_telegram_credentials(bot_token: Optional[str] = None, chat_id: Optional[str] = None):
    """Resolves Telegram Bot Token and Chat ID from arguments or environment variables."""
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    cid = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    
    token = token.strip() if token else ""
    cid = cid.strip() if cid else ""
    
    return token, cid

def send_telegram_message(message: str, bot_token: Optional[str] = None, chat_id: Optional[str] = None, parse_mode: str = "Markdown") -> Dict[str, Any]:
    """
    Sends a text message to a Telegram Chat using the Telegram Bot API.
    """
    token, cid = get_telegram_credentials(bot_token, chat_id)
    
    if not token or not cid:
        return {
            "success": False,
            "error": "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID",
            "message": "⚠️ Credenciales de Telegram incompletas. Configura el Bot Token y Chat ID."
        }
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": cid,
        "text": message,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        res_json = response.json()
        
        if response.status_code == 200 and res_json.get("ok"):
            logging.info("Telegram notification sent successfully.")
            return {"success": True, "message": "✅ Notificación enviada con éxito a Telegram."}
        else:
            err_msg = res_json.get("description", response.text)
            logging.error(f"Telegram API Error: {err_msg}")
            
            # If Markdown parsing fails, retry in plain text mode
            if "can't parse entities" in err_msg.lower():
                payload["parse_mode"] = ""
                retry_res = requests.post(url, json=payload, timeout=10).json()
                if retry_res.get("ok"):
                    return {"success": True, "message": "✅ Mensaje enviado a Telegram (modo texto sin formato)."}
                    
            return {"success": False, "error": err_msg, "message": f"❌ Error de Telegram API: {err_msg}"}
    except Exception as e:
        logging.error(f"Failed to connect to Telegram API: {e}")
        return {"success": False, "error": str(e), "message": f"❌ Error de conexión con Telegram: {str(e)}"}

def test_telegram_connection(bot_token: str, chat_id: str) -> Dict[str, Any]:
    """Sends a test message to verify Telegram credentials."""
    test_msg = (
        "⚡ *STITCH TERMINAL - PRUEBA DE CONEXIÓN*\n\n"
        "🟢 ¡El bot de Telegram está configurado y vinculado correctamente con tu Terminal de Inteligencia Cripto!"
    )
    return send_telegram_message(test_msg, bot_token=bot_token, chat_id=chat_id)

def send_breadth_alert(metrics_json: Dict[str, Any], ai_report: Optional[str] = None, bot_token: Optional[str] = None, chat_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Formats a comprehensive Market Breadth Alert and sends it to Telegram.
    """
    score = metrics_json.get("market_breadth_score", 0.0)
    tf = metrics_json.get("timeframe", "1d").upper()
    btc_price = metrics_json.get("btc_price", 0.0)
    ema20 = metrics_json.get("pct_above_ema20", 0.0)
    ema50 = metrics_json.get("pct_above_ema50", 0.0)
    ema200 = metrics_json.get("pct_above_ema200", 0.0)
    
    if score >= 80:
        regimen_badge = "🚨 SOBRECOMPRA EXTREMA / EUFORIA"
    elif score >= 60:
        regimen_badge = "🟢 SALUD ALCISTA"
    elif score >= 40:
        regimen_badge = "🟡 RÉGIMEN NEUTRO"
    elif score >= 20:
        regimen_badge = "🟠 DEBILIDAD ESTRUCTURAL"
    else:
        regimen_badge = "🔴 SOBREVENTA EXTREMA / CAPITULACIÓN"

    msg_lines = [
        f"⚡ *ALERTA DE INTELIGENCIA DE MERCADO [{tf}]*",
        f"📊 *Score de Amplitud:* `{score}/100`",
        f"🏷️ *Régimen:* {regimen_badge}",
        f"💰 *Precio BTC:* `${btc_price:,.2f}`",
        "",
        "📈 *Estructura de Medias Móviles:*",
        f"• Corto Plazo (> EMA 20): `{ema20}%` activos",
        f"• Mediano Plazo (> EMA 50): `{ema50}%` activos",
        f"• Largo Plazo (> EMA 200): `{ema200}%` activos",
    ]
    
    if ai_report:
        # Extract executive summary lines or key section
        clean_ai = ai_report.replace("---", "").strip()
        lines = [line for line in clean_ai.split("\n") if line.strip()]
        snippet = "\n".join(lines[:8])  # First few key lines
        msg_lines.extend(["", "🤖 *Resumen Ejecutivo IA:*", snippet])
        
    msg_lines.extend(["", "🔗 _Stitch Crypto Intelligence Terminal v3.0_"])
    
    full_message = "\n".join(msg_lines)
    return send_telegram_message(full_message, bot_token=bot_token, chat_id=chat_id)

if __name__ == "__main__":
    print("Testing Telegram Alerts Module...")
    res = test_telegram_connection("MOCK_TOKEN", "MOCK_CHAT_ID")
    print("Result:", res)
