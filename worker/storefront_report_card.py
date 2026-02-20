"""
Storefront Report Card generator: Creates AI-generated brief descriptions and final thoughts.

Generates concise stage descriptions and comprehensive final thoughts using OpenAI API.
"""

from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

from openai import OpenAI
from shared.config import get_config
from shared.logging import get_logger

logger = get_logger(__name__)


def generate_stage_description(stage: str, score: float, stage_summary: str, model: str = "gpt-5.2") -> tuple[str, dict]:
    """
    Generate a brief description for a stage based on score and summary.
    
    Args:
        stage: Stage name (Awareness/Consideration/Conversion)
        score: Stage score (0-100)
        stage_summary: Full stage summary text
        model: OpenAI model to use
        
    Returns:
        Tuple of (description: str, token_usage: dict with input_tokens, output_tokens, cost_usd)
    """
    api_key = os.getenv("OPENAI_API_KEY")
    input_per_1m = float(os.getenv("OPENAI_PRICE_INPUT_PER_1M", "2.50"))
    output_per_1m = float(os.getenv("OPENAI_PRICE_OUTPUT_PER_1M", "10.00"))
    
    if not api_key:
        logger.warning("openai_api_key_missing_for_stage_description", stage=stage)
        fallback = f"Strong performance in {stage.lower()} stage" if score >= 80 else (f"Moderate performance in {stage.lower()} stage with room for improvement" if score >= 50 else f"Weak performance in {stage.lower()} stage requiring attention")
        return fallback, {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    
    client = OpenAI(api_key=api_key)
    
    prompt = f"""Generate a brief, concise description (1-2 sentences, max 100 characters) for the {stage} stage of a website audit.

Stage Score: {score}/100
Stage Summary: {stage_summary[:500]}

The description should:
- Be professional and actionable
- Highlight the key strength or weakness
- Be suitable for display in a report card format
- Match the tone: positive for high scores (80+), balanced for medium (50-79), concerned for low (<50)

Return only the description text, no quotes or formatting."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert e-commerce consultant providing concise, actionable insights.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.7,
            max_completion_tokens=100,
        )
        
        description = response.choices[0].message.content.strip()
        
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        cost_usd = (input_tokens / 1_000_000 * input_per_1m) + (output_tokens / 1_000_000 * output_per_1m)
        
        return description, {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
        }
        
    except Exception as e:
        logger.error(
            "stage_description_generation_failed",
            stage=stage,
            error=str(e),
            error_type=type(e).__name__,
        )
        fallback = f"Strong performance in {stage.lower()} stage" if score >= 80 else (f"Moderate performance in {stage.lower()} stage" if score >= 50 else f"Weak performance in {stage.lower()} stage")
        return fallback, {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


def generate_final_thoughts(
    url: str,
    stage_scores: dict,
    stage_summaries: list[dict],
    actionable_findings: list[dict],
    overall_score: float,
    model: str = "gpt-5.2",
) -> tuple[str, dict]:
    """
    Generate comprehensive final thoughts for the storefront report card.
    
    Args:
        url: Website URL being audited
        stage_scores: Dict with stage scores {awareness: float, consideration: float, conversion: float}
        stage_summaries: List of stage summary dicts
        actionable_findings: List of actionable finding dicts
        overall_score: Overall weighted score (0-100)
        model: OpenAI model to use
        
    Returns:
        Tuple of (final_thoughts: str, token_usage: dict with input_tokens, output_tokens, cost_usd)
    """
    api_key = os.getenv("OPENAI_API_KEY")
    input_per_1m = float(os.getenv("OPENAI_PRICE_INPUT_PER_1M", "2.50"))
    output_per_1m = float(os.getenv("OPENAI_PRICE_OUTPUT_PER_1M", "10.00"))
    
    if not api_key:
        logger.warning("openai_api_key_missing_for_final_thoughts")
        return "Final thoughts generation unavailable (OpenAI API key not configured).", {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    
    client = OpenAI(api_key=api_key)
    
    stage_summaries_text = "\n\n".join([
        f"{s['stage']} Stage ({stage_scores.get(s['stage'].lower(), 0):.1f}%): {s['summary'][:300]}"
        for s in stage_summaries
    ])
    
    high_priority_findings = [f for f in actionable_findings if f.get("impact") == "High"][:5]
    findings_text = "\n".join([
        f"- {f['actionable_finding']}"
        for f in high_priority_findings
    ])
    
    prompt = f"""Generate final thoughts for a storefront report card audit.

Website: {url}
Overall Score: {overall_score}/100

Stage Scores:
- Awareness: {stage_scores.get('awareness', 0):.1f}%
- Consideration: {stage_scores.get('consideration', 0):.1f}%
- Conversion: {stage_scores.get('conversion', 0):.1f}%

Stage Summaries:
{stage_summaries_text}

Top Priority Findings:
{findings_text}

Generate exactly 5 sentences of final thoughts that:
1. Provide an executive summary of overall performance
2. Highlight the most critical opportunities for improvement
3. Connect the stage scores to business impact
4. Offer strategic recommendations prioritized by impact
5. Be professional, actionable, and revenue-focused

Output Requirements:
- Write exactly 5 sentences, no more, no less
- Write as a single paragraph (no line breaks between sentences)
- Each sentence should be substantial and meaningful
- Be professional, actionable, and revenue-focused
- Write in a clear, professional tone suitable for business stakeholders

Return only the 5-sentence paragraph text, no quotes or formatting."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert e-commerce consultant providing strategic insights for website optimization and revenue recovery.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.7,
            max_completion_tokens=400,
        )
        
        final_thoughts = response.choices[0].message.content.strip()
        
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        
        cost_usd = (input_tokens / 1_000_000 * input_per_1m) + (output_tokens / 1_000_000 * output_per_1m)
        
        logger.info(
            "final_thoughts_generated",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
        )
        
        return final_thoughts, {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": cost_usd,
        }
        
    except Exception as e:
        logger.error(
            "final_thoughts_generation_failed",
            error=str(e),
            error_type=type(e).__name__,
        )
        return f"Final thoughts generation failed: {str(e)}", {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


def generate_storefront_report_card(
    url: str,
    stage_scores: dict,
    stage_summaries: list[dict],
    actionable_findings: list[dict],
    overall_score: float,
    model: str = "gpt-5.2",
) -> dict:
    """
    Generate complete storefront report card data.
    
    Returns dict with:
    - stage_descriptions: {awareness: str, consideration: str, conversion: str}
    - final_thoughts: str
    - token_usage: dict with aggregated input_tokens, output_tokens, cost_usd
    - model_version: str
    """
    stage_descriptions = {}
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost_usd = 0.0
    
    for stage in ["Awareness", "Consideration", "Conversion"]:
        stage_key = stage.lower()
        score = stage_scores.get(stage_key, 0.0)
        stage_summary_obj = next((s for s in stage_summaries if s.get("stage") == stage), None)
        summary_text = stage_summary_obj.get("summary", "") if stage_summary_obj else ""
        
        description, token_data = generate_stage_description(stage, score, summary_text, model)
        stage_descriptions[stage_key] = description
        total_input_tokens += token_data.get("input_tokens", 0)
        total_output_tokens += token_data.get("output_tokens", 0)
        total_cost_usd += token_data.get("cost_usd", 0.0)
    
    final_thoughts, final_token_data = generate_final_thoughts(
        url, stage_scores, stage_summaries, actionable_findings, overall_score, model
    )
    total_input_tokens += final_token_data.get("input_tokens", 0)
    total_output_tokens += final_token_data.get("output_tokens", 0)
    total_cost_usd += final_token_data.get("cost_usd", 0.0)
    
    return {
        "stage_descriptions": stage_descriptions,
        "final_thoughts": final_thoughts,
        "token_usage": {
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
        },
        "cost_usd": total_cost_usd,
        "model_version": model,
    }
