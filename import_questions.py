#!/usr/bin/env python3
"""
Import questions from CSV file into audit_questions table.
"""

import csv
import os
import sys

from shared.db import get_audit_questions_table, get_db_session


def normalize_page_type(page: str) -> str:
    """Normalize page type from CSV to database format."""
    page_lower = page.lower().strip()
    mapping = {
        "homepage": "homepage",
        "product": "product",
        "pdp": "product",
        "cart": "cart",
        "checkout": "checkout",
        "navigation": "navigation",
        "collection": "collection",
        "404 page": "404",
        "404": "404",
    }
    return mapping.get(page_lower, page_lower)


def parse_csv(csv_path: str) -> list[dict]:
    """Parse CSV file and extract questions."""
    questions = []

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

        current_category = None

        for i, row in enumerate(rows):
            if i == 0:
                continue

            if len(row) < 8:
                continue

            category = row[0].strip() if row[0] else ""
            question = row[1].strip() if len(row) > 1 and row[1] else ""
            ai_criteria = row[2].strip() if len(row) > 2 and row[2] else ""
            tier = row[3].strip() if len(row) > 3 and row[3] else ""
            severity = row[4].strip() if len(row) > 4 and row[4] else ""
            page = row[5].strip() if len(row) > 5 and row[5] else ""
            bar_chart = row[6].strip() if len(row) > 6 and row[6] else ""
            exact_fix = row[7].strip() if len(row) > 7 and row[7] else ""

            if category and not question:
                current_category = category
                continue

            if question and tier and severity and page:
                try:
                    tier_int = int(tier)
                    severity_int = int(severity)

                    if tier_int < 1 or tier_int > 3:
                        print(f"Warning: Invalid tier {tier_int} for question: {question[:50]}...")
                        continue

                    if severity_int < 1 or severity_int > 5:
                        short = question[:50]
                        print(f"Warning: Invalid severity {severity_int} for question: {short}...")
                        continue

                    page_normalized = normalize_page_type(page)
                    if page_normalized not in [
                        "homepage",
                        "product",
                        "cart",
                        "checkout",
                        "navigation",
                        "collection",
                        "404",
                    ]:
                        print(
                            f"Warning: Invalid page type '{page}' for question: {question[:50]}..."
                        )
                        continue

                    questions.append(
                        {
                            "category": current_category or category or "Unknown",
                            "question": question,
                            "ai_criteria": ai_criteria,
                            "tier": tier_int,
                            "severity": severity_int,
                            "page_type": page_normalized,
                            "bar_chart_category": bar_chart or "Other",
                            "exact_fix": exact_fix or "",
                        }
                    )
                except ValueError as e:
                    short = question[:50]
                    print(f"Warning: Invalid tier/severity for question: {short}... Error: {e}")
                    continue

    return questions


def insert_questions(questions: list[dict]) -> int:
    """Insert questions into database."""
    inserted = 0
    skipped = 0

    for q in questions:
        with get_db_session() as session:
            questions_table = get_audit_questions_table()

            try:
                insert_stmt = questions_table.insert().values(
                    category=q["category"],
                    question=q["question"],
                    ai_criteria=q["ai_criteria"],
                    tier=q["tier"],
                    severity=q["severity"],
                    bar_chart_category=q["bar_chart_category"],
                    exact_fix=q["exact_fix"],
                    page_type=q["page_type"],
                )
                session.execute(insert_stmt)
                session.commit()
                inserted += 1
            except Exception as e:
                session.rollback()
                error_msg = str(e)
                if "duplicate" in error_msg.lower() or "unique" in error_msg.lower():
                    skipped += 1
                else:
                    print(f"Error inserting question '{q['question'][:50]}...': {error_msg[:200]}")
                continue

    if skipped > 0:
        print(f"Skipped {skipped} duplicate questions")
    return inserted


def main():
    csv_path = os.getenv("CSV_PATH", "/app/questions.csv")

    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)

    print(f"Parsing CSV file: {csv_path}")
    questions = parse_csv(csv_path)
    print(f"Found {len(questions)} valid questions")

    if not questions:
        print("No questions to insert!")
        sys.exit(1)

    print(f"\nInserting {len(questions)} questions into database...")
    inserted = insert_questions(questions)
    print(f"Successfully inserted {inserted} questions!")


if __name__ == "__main__":
    main()
