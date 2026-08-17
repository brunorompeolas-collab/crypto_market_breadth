from typing import Dict, Any, List

def determine_data_status(assets_valid: int, total_universe: int, ema20_valid: int, ema50_valid: int, ema200_valid: int) -> str:
    """
    P0.13: Deterministic Data Quality Formula
    Considers universe coverage and EMA coverage.
    """
    coverage_pct = (assets_valid / total_universe) * 100 if total_universe > 0 else 0
    ema200_coverage = (ema200_valid / assets_valid) * 100 if assets_valid > 0 else 0
    
    # Penalize if EMA200 is missing for many assets
    effective_score = coverage_pct * 0.7 + ema200_coverage * 0.3
    
    if effective_score >= 90: return "HIGH"
    if effective_score >= 75: return "GOOD"
    if effective_score >= 50: return "LIMITED"
    return "LOW"

def evaluate_divergence(recent_trend: List[Dict[str, Any]], benchmark: str = 'BTC') -> Dict[str, str]:
    """
    P0.11 & P0.6: Deterministic Divergence Engine.
    Compares 7-period change in generic benchmark vs 7-period change in breadth.
    """
    if len(recent_trend) < 2:
        return {
            "type": "NEUTRAL / INCONCLUSIVE",
            "desc": "No hay suficientes datos históricos para detectar divergencias.",
            "metrics": ""
        }
        
    first_snap = recent_trend[0]
    last_snap = recent_trend[-1]
    
    b_key = 'btc_price' if benchmark == 'BTC' else 'eth_price'
    
    first_price = first_snap.get(b_key, 0.0)
    last_price = last_snap.get(b_key, 0.0)
    first_score = first_snap.get('breadth_score', 0.0)
    last_score = last_snap.get('breadth_score', 0.0)
    
    if first_price == 0.0:
        return {"type": "NEUTRAL / INCONCLUSIVE", "desc": "Precio base 0", "metrics": ""}
        
    price_change_pct = ((last_price - first_price) / first_price) * 100
    score_change = last_score - first_score
    
    metrics_str = f"{benchmark} 7-period change: {price_change_pct:+.1f}%\nBreadth change: {score_change:+.1f} points"
    
    if price_change_pct <= 0.5 and score_change >= 5.0:
        div_type = "BULLISH BREADTH DIVERGENCE"
        div_desc = f"El precio de {benchmark} retrocedió o lateralizó, pero la amplitud mejoró. Indica acumulación silenciosa."
    elif price_change_pct >= 0.5 and score_change <= -5.0:
        div_type = "BEARISH BREADTH DIVERGENCE"
        div_desc = f"El precio de {benchmark} subió, pero la amplitud se deterioró. Indica debilidad estructural."
    elif price_change_pct > 2.0 and score_change > 2.0:
        div_type = "ALIGNED EXPANSION"
        div_desc = f"El precio de {benchmark} y la amplitud crecen orgánicamente juntos."
    elif price_change_pct < -2.0 and score_change < -2.0:
        div_type = "ALIGNED DETERIORATION"
        div_desc = f"El precio de {benchmark} y la amplitud caen de la mano, confirmando presión vendedora."
    else:
        div_type = "NEUTRAL / INCONCLUSIVE"
        div_desc = f"Precio de {benchmark} y amplitud no muestran divergencias extremas significativas."
        
    return {
        "type": div_type,
        "desc": div_desc,
        "metrics": metrics_str
    }
