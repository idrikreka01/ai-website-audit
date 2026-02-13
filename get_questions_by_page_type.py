"""
Script to get audit questions for a specific page type in JSON format.

Usage:
    python get_questions_by_page_type.py homepage
    python get_questions_by_page_type.py product
    python get_questions_by_page_type.py cart
    python get_questions_by_page_type.py checkout
"""

import json
import sys
from shared.db import get_audit_questions_table, get_db_session
from sqlalchemy import select


def get_questions_by_page_type(page_type: str) -> dict:
    """
    Get all questions for a specific page type.
    
    Returns a dict in the format:
    {
        "question": {
            "{question_id}": {
                "ai": "..."
            },
            ...
        }
    }
    """
    valid_page_types = {"homepage", "product", "cart", "checkout"}
    
    page_type_lower = page_type.lower().strip()
    
    if page_type_lower == "cart page" or page_type_lower == "cart":
        normalized_page_type = "cart"
    elif page_type_lower == "product page" or page_type_lower == "pdp" or page_type_lower == "product":
        normalized_page_type = "product"
    elif page_type_lower in {"home page", "homepage", "home", "landing"}:
        normalized_page_type = "homepage"
    elif page_type_lower == "checkout page" or page_type_lower == "checkout":
        normalized_page_type = "checkout"
    elif page_type_lower in valid_page_types:
        normalized_page_type = page_type_lower
    else:
        raise ValueError(f"Invalid page_type '{page_type}'. Must be one of: {', '.join(valid_page_types)} (or variations like 'cart page', 'product page', 'pdp', etc.)")
    
    page_type = normalized_page_type
    
    with get_db_session() as session:
        questions_table = get_audit_questions_table()
        
        stmt = select(questions_table).where(
            questions_table.c.page_type == page_type
        ).order_by(questions_table.c.question_id)
        
        results = session.execute(stmt).all()
        
        questions_dict = {}
        
        for row in results:
            question = dict(row._mapping)
            question_id = str(question["question_id"])
            ai_criteria = question["ai_criteria"]
            
            questions_dict[question_id] = {
                "ai": ai_criteria
            }
        
        return {
            "question": questions_dict
        }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python get_questions_by_page_type.py <page_type>")
        print("Page types: homepage, product, cart, checkout")
        sys.exit(1)
    
    page_type = sys.argv[1]
    
    try:
        result = get_questions_by_page_type(page_type)
        print(json.dumps(result, indent=2))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
