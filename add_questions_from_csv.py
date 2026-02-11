"""
Script to add audit questions from CSV file to the database.

Reads questions from a CSV file and inserts them into the audit_questions table
using the new schema (question_id, category, question, ai_criteria, tier, severity,
bar_chart_category, exact_fix, page_type).
"""

import csv
import os
import sys
from pathlib import Path

from shared.db import get_audit_questions_table, get_db_session


def normalize_page_type(page_type: str) -> str:
    """Normalize page_type to valid values."""
    page_type = page_type.strip().lower()
    valid_types = {"homepage", "product", "cart", "checkout"}
    
    if page_type in valid_types:
        return page_type
    
    if page_type in {"home", "home page", "landing"}:
        return "homepage"
    if page_type in {"product page", "pdp", "product detail"}:
        return "product"
    if page_type in {"shopping cart", "basket"}:
        return "cart"
    if page_type in {"checkout page", "payment"}:
        return "checkout"
    
    return "homepage"


def validate_row(row: dict, row_num: int) -> tuple[bool, dict | None, str]:
    """Validate a CSV row and return (is_valid, data_dict, error_message)."""
    try:
        category = row.get("Category", "").strip()
        question = row.get("question", "").strip()
        ai_criteria = row.get("ai", "").strip()
        tier_str = row.get("tier", "").strip()
        severity_str = row.get("severity", "").strip()
        bar_chart_category = row.get("Bar Chart Category (In Audit)", "").strip()
        exact_fix = row.get("Exact Fix:", "").strip()
        page_type = row.get("page_type", "").strip()
        
        if not category:
            return False, None, f"Row {row_num}: Missing 'Category'"
        if not question:
            return False, None, f"Row {row_num}: Missing 'question'"
        if not ai_criteria:
            return False, None, f"Row {row_num}: Missing 'ai'"
        if not bar_chart_category:
            return False, None, f"Row {row_num}: Missing 'Bar Chart Category (In Audit)'"
        if not exact_fix:
            return False, None, f"Row {row_num}: Missing 'Exact Fix:'"
        if not page_type:
            return False, None, f"Row {row_num}: Missing 'page_type'"
        
        try:
            tier = int(tier_str)
            if tier < 1 or tier > 3:
                return False, None, f"Row {row_num}: 'tier' must be 1-3, got {tier}"
        except ValueError:
            return False, None, f"Row {row_num}: 'tier' must be an integer, got '{tier_str}'"
        
        try:
            severity = int(severity_str)
            if severity < 1 or severity > 5:
                return False, None, f"Row {row_num}: 'severity' must be 1-5, got {severity}"
        except ValueError:
            return False, None, f"Row {row_num}: 'severity' must be an integer, got '{severity_str}'"
        
        normalized_page_type = normalize_page_type(page_type)
        
        return True, {
            "category": category,
            "question": question,
            "ai_criteria": ai_criteria,
            "tier": tier,
            "severity": severity,
            "bar_chart_category": bar_chart_category,
            "exact_fix": exact_fix,
            "page_type": normalized_page_type,
        }, ""
    
    except Exception as e:
        return False, None, f"Row {row_num}: Error validating row: {str(e)}"


def add_questions_from_csv(csv_path: str) -> None:
    """Read questions from CSV and add them to the database."""
    csv_path = Path(csv_path)
    if not csv_path.exists():
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)
    
    print(f"Reading questions from: {csv_path}")
    
    questions_to_add = []
    errors = []
    
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):
            is_valid, data, error = validate_row(row, row_num)
            if is_valid:
                questions_to_add.append(data)
            else:
                errors.append(error)
    
    if errors:
        print(f"\n⚠️  Validation errors found ({len(errors)} errors):")
        for error in errors[:10]:
            print(f"  - {error}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more errors")
        print(f"\n❌ Aborting. Please fix errors in CSV file.")
        sys.exit(1)
    
    if not questions_to_add:
        print("❌ No valid questions found in CSV file.")
        sys.exit(1)
    
    print(f"✅ Found {len(questions_to_add)} valid questions")
    
    with get_db_session() as session:
        questions_table = get_audit_questions_table()
        
        added_count = 0
        skipped_count = 0
        
        for question_data in questions_to_add:
            try:
                insert_stmt = questions_table.insert().values(**question_data)
                session.execute(insert_stmt)
                added_count += 1
            except Exception as e:
                error_msg = str(e).lower()
                if "unique" in error_msg or "duplicate" in error_msg:
                    skipped_count += 1
                    print(f"⚠️  Skipped duplicate question: {question_data['question'][:60]}...")
                else:
                    print(f"❌ Error adding question '{question_data['question'][:60]}...': {e}")
                    raise
        
        session.commit()
        
        print(f"\n✅ Successfully added {added_count} questions")
        if skipped_count > 0:
            print(f"⚠️  Skipped {skipped_count} duplicate questions")


if __name__ == "__main__":
    csv_file = os.getenv("CSV_FILE", "/Users/rinor/Downloads/Untitled spreadsheet - Sheet1.csv")
    
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
    
    print("=" * 60)
    print("Add Questions from CSV")
    print("=" * 60)
    print(f"\nCSV file: {csv_file}")
    print("\n⚠️  IMPORTANT: Make sure migration 0010 has been run first!")
    print("   Run: docker-compose exec api alembic upgrade head")
    print("\n" + "=" * 60 + "\n")
    
    add_questions_from_csv(csv_file)
