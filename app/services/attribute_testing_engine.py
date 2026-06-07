"""
Attribute Testing Engine — Complifyre EVE
Executes attribute tests on uploaded data files.
"""

import pandas as pd
import numpy as np
from typing import Any
import logging

logger = logging.getLogger(__name__)


class AttributeTestingEngine:
    """
    Core engine for executing attribute tests on uploaded datasets.
    
    Workflow:
    1. Load uploaded file (Excel/CSV)
    2. Detect columns using AI-generated descriptions
    3. Apply sequential filters to get population
    4. Test each attribute on the population
    5. Generate exception list and statistics
    6. Produce audit findings
    """

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.df = None
        self.column_map = {}  # Maps description → actual column name
        self.results = {}

    # ─────────────────────────────────────────────
    # STEP 1: Load File
    # ─────────────────────────────────────────────
    def load_file(self) -> dict:
        """Load Excel or CSV file into DataFrame."""
        try:
            if self.file_path.endswith('.csv'):
                self.df = pd.read_csv(self.file_path)
            else:
                self.df = pd.read_excel(self.file_path)
            
            logger.info(f"File loaded: {len(self.df)} rows, {len(self.df.columns)} columns")
            return {
                "status": "success",
                "total_rows": len(self.df),
                "columns": list(self.df.columns),
                "sample_rows": self.df.head(3).to_dict(orient='records')
            }
        except Exception as e:
            logger.error(f"File load error: {e}")
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # STEP 2: AI Column Mapping
    # ─────────────────────────────────────────────
    def map_columns_with_ai(self, attribute_descriptions: list[str]) -> dict:
        """
        Use AI to map natural language column descriptions 
        to actual column names in the uploaded file.
        
        e.g. "Loan Type column" → "loan_type" or "LoanType" or "Type of Loan"
        """
        import anthropic
        
        columns = list(self.df.columns)
        sample = self.df.head(3).to_dict(orient='records')
        
        prompt = f"""
You are a data analyst. You have a dataset with these columns:
{columns}

Sample data (first 3 rows):
{sample}

Map each of these natural language descriptions to the BEST matching column name:
{attribute_descriptions}

Return ONLY a JSON object like:
{{
  "Loan Type column": "actual_column_name",
  "Interest Rate column": "actual_column_name",
  ...
}}

If no good match exists, use null.
"""
        try:
            client = anthropic.Anthropic()
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}]
            )
            import json
            mapping = json.loads(response.content[0].text)
            self.column_map = mapping
            return {"status": "success", "mapping": mapping}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ─────────────────────────────────────────────
    # STEP 3: Apply Filters — Get Population
    # ─────────────────────────────────────────────
    def apply_filters(self, filters: list[dict]) -> pd.DataFrame:
        """
        Apply sequential filters to get the relevant population.
        
        filters = [
            {"column_description": "Loan Type column", "filter_value": "Home Loan", "filter_type": "equals"},
            {"column_description": "Applicant Category column", "filter_value": "BPL", "filter_type": "equals"}
        ]
        """
        filtered_df = self.df.copy()
        
        for f in filters:
            col_desc = f.get("column_description")
            actual_col = self.column_map.get(col_desc)
            
            if not actual_col or actual_col not in filtered_df.columns:
                logger.warning(f"Column not found for: {col_desc}")
                continue
            
            value = f.get("filter_value")
            filter_type = f.get("filter_type", "equals")
            
            if filter_type == "equals":
                filtered_df = filtered_df[
                    filtered_df[actual_col].astype(str).str.strip().str.lower() == str(value).strip().lower()
                ]
            elif filter_type == "contains":
                filtered_df = filtered_df[
                    filtered_df[actual_col].astype(str).str.contains(str(value), case=False, na=False)
                ]
            elif filter_type == "greater_than":
                filtered_df = filtered_df[pd.to_numeric(filtered_df[actual_col], errors='coerce') > float(value)]
            elif filter_type == "less_than":
                filtered_df = filtered_df[pd.to_numeric(filtered_df[actual_col], errors='coerce') < float(value)]
            elif filter_type == "not_equals":
                filtered_df = filtered_df[
                    filtered_df[actual_col].astype(str).str.strip().str.lower() != str(value).strip().lower()
                ]
            
            logger.info(f"After filter '{col_desc} {filter_type} {value}': {len(filtered_df)} rows")
        
        return filtered_df

    # ─────────────────────────────────────────────
    # STEP 4: Test Attribute
    # ─────────────────────────────────────────────
    def test_attribute(self, population_df: pd.DataFrame, attribute: dict) -> dict:
        """
        Test a single attribute on the filtered population.
        Returns pass/fail per row + statistics.
        """
        test_col_desc = attribute.get("test_column_description")
        actual_col = self.column_map.get(test_col_desc)
        test_type = attribute.get("test_type")
        threshold = attribute.get("threshold")
        identifier_desc = attribute.get("exception_identifier_column")
        actual_id_col = self.column_map.get(identifier_desc)

        if not actual_col or actual_col not in population_df.columns:
            return {
                "status": "error",
                "message": f"Test column not found: {test_col_desc}"
            }

        results_df = population_df.copy()
        
        # Apply test based on type
        if test_type == "numeric_threshold":
            threshold_val = float(threshold)
            test_condition = attribute.get("test_condition", "")
            
            numeric_col = pd.to_numeric(results_df[actual_col], errors='coerce')
            
            if "not exceed" in test_condition or "<=" in test_condition:
                results_df["__pass__"] = numeric_col <= threshold_val
                results_df["__actual__"] = numeric_col
                results_df["__expected__"] = f"≤ {threshold_val}{attribute.get('threshold_unit', '')}"
            elif "exceed" in test_condition or ">=" in test_condition:
                results_df["__pass__"] = numeric_col >= threshold_val
                results_df["__actual__"] = numeric_col
                results_df["__expected__"] = f"≥ {threshold_val}{attribute.get('threshold_unit', '')}"
            elif "less than" in test_condition or "<" in test_condition:
                results_df["__pass__"] = numeric_col < threshold_val
                results_df["__actual__"] = numeric_col
                results_df["__expected__"] = f"< {threshold_val}{attribute.get('threshold_unit', '')}"

        elif test_type == "presence_check":
            results_df["__pass__"] = results_df[actual_col].notna() & (results_df[actual_col].astype(str).str.strip() != "")
            results_df["__actual__"] = results_df[actual_col].apply(lambda x: "Present" if pd.notna(x) and str(x).strip() != "" else "Missing")
            results_df["__expected__"] = "Present"

        elif test_type == "value_match":
            expected_val = attribute.get("expected_value", "")
            results_df["__pass__"] = results_df[actual_col].astype(str).str.strip().str.lower() == str(expected_val).strip().lower()
            results_df["__actual__"] = results_df[actual_col]
            results_df["__expected__"] = expected_val

        elif test_type == "date_difference":
            # For TAT testing — calculate days between two dates
            # Will be enhanced based on specific use cases
            threshold_val = float(threshold)
            results_df["__numeric__"] = pd.to_numeric(results_df[actual_col], errors='coerce')
            results_df["__pass__"] = results_df["__numeric__"] <= threshold_val
            results_df["__actual__"] = results_df["__numeric__"]
            results_df["__expected__"] = f"≤ {threshold_val} {attribute.get('threshold_unit', 'days')}"

        # Get exceptions (failed rows)
        exceptions_df = results_df[~results_df["__pass__"]]
        passed_df = results_df[results_df["__pass__"]]
        
        # Build exception list
        exception_list = []
        for _, row in exceptions_df.iterrows():
            exc = {
                "identifier": str(row[actual_id_col]) if actual_id_col and actual_id_col in row.index else "N/A",
                "actual_value": str(row.get("__actual__", "N/A")),
                "expected_value": str(row.get("__expected__", "N/A")),
                "failed_attribute": attribute.get("attribute_name")
            }
            # Include all original columns for context
            for col in population_df.columns:
                exc[col] = str(row[col])
            exception_list.append(exc)

        # Statistics
        total_population = len(results_df)
        total_exceptions = len(exceptions_df)
        exception_rate = (total_exceptions / total_population * 100) if total_population > 0 else 0
        population_impact = (total_exceptions / len(self.df) * 100) if len(self.df) > 0 else 0

        return {
            "status": "success",
            "attribute_name": attribute.get("attribute_name"),
            "population_tested": total_population,
            "passed": len(passed_df),
            "exceptions": total_exceptions,
            "exception_rate": round(exception_rate, 2),
            "population_impact": round(population_impact, 2),
            "exception_list": exception_list,
            "severity": attribute.get("severity_if_failed"),
            "regulatory_reference": attribute.get("regulatory_reference"),
            "pass_criteria": attribute.get("pass_criteria"),
            "fail_criteria": attribute.get("fail_criteria")
        }

    # ─────────────────────────────────────────────
    # STEP 2B: Period Filter
    # ─────────────────────────────────────────────
    def apply_period_filter(
        self,
        audit_start: str,
        audit_end: str,
    ) -> dict:
        """
        Auto-detect date column(s) and filter rows to audit period.
        Organization/entity check is intentionally skipped — data
        files from internal systems often do not carry entity name.

        Returns:
        {
            "total_rows": 500,
            "within_period": 347,
            "excluded": 153,
            "date_column_used": "Disbursement Date",
            "period_applied": "2024-04-01 to 2025-03-31",
            "filtered_df": <DataFrame of 347 rows>
        }
        """
        import anthropic, json, re as _re
        from datetime import datetime

        total_rows = len(self.df)
        columns = list(self.df.columns)
        sample = self.df.head(5).to_dict(orient="records")

        # Ask LLM to identify the most relevant date column
        prompt = f"""You are a data analyst reviewing an audit dataset.

Dataset columns: {columns}
Sample rows (first 5): {json.dumps(sample, default=str)}

Audit period: {audit_start} to {audit_end}

Task: Identify the SINGLE most relevant date column that represents when
each transaction/event occurred (e.g. Disbursement Date, Transaction Date,
Approval Date, Effective Date). This column will be used to filter records
within the audit period.

Return ONLY this JSON:
{{
  "date_column": "exact column name or null if none found",
  "confidence": "HIGH | MEDIUM | LOW",
  "reason": "one sentence explanation"
}}"""

        try:
            from app import client as _openai_client
            response = _openai_client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.choices[0].message.content.strip()
            result = json.loads(raw)
        except Exception as e:
            logger.warning(f"Period filter LLM call failed: {e}")
            return {
                "total_rows": total_rows,
                "within_period": total_rows,
                "excluded": 0,
                "date_column_used": None,
                "period_applied": None,
                "note": f"Period filter skipped — LLM error: {e}",
                "filtered_df": self.df,
            }

        date_col = result.get("date_column")
        if not date_col or date_col not in self.df.columns:
            return {
                "total_rows": total_rows,
                "within_period": total_rows,
                "excluded": 0,
                "date_column_used": None,
                "period_applied": None,
                "note": "Period filter not applied — no date column identified in dataset",
                "filtered_df": self.df,
            }

        # Parse dates
        try:
            parsed_dates = pd.to_datetime(self.df[date_col], errors="coerce", dayfirst=True)
            start_dt = pd.Timestamp(audit_start)
            end_dt   = pd.Timestamp(audit_end)

            mask = (parsed_dates >= start_dt) & (parsed_dates <= end_dt)
            filtered = self.df[mask].copy()
            within  = int(mask.sum())
            excluded = total_rows - within

            logger.info(
                f"[Period filter] Column='{date_col}' | "
                f"Total={total_rows} | Within period={within} | Excluded={excluded}"
            )

            return {
                "total_rows": total_rows,
                "within_period": within,
                "excluded": excluded,
                "date_column_used": date_col,
                "period_applied": f"{audit_start} to {audit_end}",
                "note": result.get("reason", ""),
                "filtered_df": filtered,
            }
        except Exception as e:
            logger.warning(f"Period date parsing failed: {e}")
            return {
                "total_rows": total_rows,
                "within_period": total_rows,
                "excluded": 0,
                "date_column_used": date_col,
                "period_applied": None,
                "note": f"Date parsing failed — testing all rows: {e}",
                "filtered_df": self.df,
            }

    # ─────────────────────────────────────────────
    # STEP 5: Run All Attributes
    # ─────────────────────────────────────────────
    def run_all_attributes(self, test_attributes: list[dict]) -> dict:
        """
        Run all attributes in sequence.
        Respects testing_sequence and depends_on_attribute.
        """
        # Sort by testing sequence
        sorted_attributes = sorted(test_attributes, key=lambda x: x.get("testing_sequence", 1))
        
        all_results = []
        total_exceptions = 0
        highest_severity = "Minor"
        severity_order = {"Critical": 4, "Major": 3, "Significant": 2, "Minor": 1}
        
        for attr in sorted_attributes:
            # Check dependency
            depends_on = attr.get("depends_on_attribute")
            if depends_on:
                # Find the dependent attribute result
                dep_result = next((r for r in all_results if r["attribute_name"] == depends_on), None)
                if dep_result and dep_result["exceptions"] > 0:
                    logger.info(f"Skipping {attr['attribute_name']} — dependency {depends_on} failed")
                    continue

            # Apply filters
            population_df = self.apply_filters(attr.get("population_filters", []))
            
            if len(population_df) == 0:
                all_results.append({
                    "attribute_name": attr.get("attribute_name"),
                    "status": "no_population",
                    "message": "No records matched the filter criteria",
                    "population_tested": 0,
                    "exceptions": 0,
                    "exception_rate": 0
                })
                continue
            
            # Test attribute
            result = self.test_attribute(population_df, attr)
            all_results.append(result)
            
            # Track totals
            if result.get("status") == "success":
                total_exceptions += result.get("exceptions", 0)
                attr_severity = result.get("severity", "Minor")
                if result.get("exceptions", 0) > 0:
                    if severity_order.get(attr_severity, 1) > severity_order.get(highest_severity, 1):
                        highest_severity = attr_severity
        
        return {
            "attribute_results": all_results,
            "total_attributes_tested": len(all_results),
            "total_exceptions_found": total_exceptions,
            "overall_severity": highest_severity if total_exceptions > 0 else "No exceptions",
            "total_population": len(self.df)
        }

    # ─────────────────────────────────────────────
    # STEP 6: Generate Audit Finding
    # ─────────────────────────────────────────────
    def generate_audit_finding(self, test_results: dict, activity_name: str) -> str:
        """
        Auto-generate audit finding paragraph from test results.
        """
        import anthropic
        import json
        
        prompt = f"""
You are an expert auditor. Based on these attribute test results, generate a professional audit finding.

Control Activity: {activity_name}

Test Results:
{json.dumps(test_results, indent=2)}

Generate:
1. CONDITION: What was found (specific numbers, exception IDs)
2. CRITERIA: What should have been (regulatory requirement)
3. EFFECT/RISK: Impact of this finding
4. EXCEPTION RATE ANALYSIS: Statistical significance

Use professional audit language. Be specific about exception counts, rates, and identifiers.
Format in clear paragraphs.
"""
        try:
            client = anthropic.Anthropic()
            response = client.messages.create(
                model="claude-opus-4-6",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        except Exception as e:
            return f"Finding generation error: {e}"


# ─────────────────────────────────────────────
# Convenience function for route integration
# ─────────────────────────────────────────────
def run_attribute_testing(
    file_path: str,
    test_attributes: list[dict],
    activity_name: str,
    audit_period_start: str = None,
    audit_period_end: str = None,
) -> dict:
    """
    Main entry point for attribute testing.
    Called from route when auditor uploads data file.
    Now supports:
    - Period filtering (audit_period_start / audit_period_end)
    - Column inventory (which columns were tested)
    """
    engine = AttributeTestingEngine(file_path)

    # Load file
    load_result = engine.load_file()
    if load_result["status"] == "error":
        return load_result

    # ── Column inventory: collect all descriptions needed ──────
    col_descriptions = []
    for attr in test_attributes:
        for f in attr.get("population_filters", []):
            col_descriptions.append(f.get("column_description"))
        col_descriptions.append(attr.get("test_column_description"))
        col_descriptions.append(attr.get("exception_identifier_column"))

    col_descriptions = list(set(filter(None, col_descriptions)))

    # Map columns with AI
    mapping_result = engine.map_columns_with_ai(col_descriptions)
    if mapping_result["status"] == "error":
        return mapping_result

    # Build column inventory — natural description → actual column name
    column_inventory = {
        desc: engine.column_map.get(desc)
        for desc in col_descriptions
        if engine.column_map.get(desc)
    }

    # ── Period filter ──────────────────────────────────────────
    period_stats = None
    if audit_period_start and audit_period_end:
        period_result = engine.apply_period_filter(audit_period_start, audit_period_end)
        period_stats = {
            "total_rows_in_file": period_result["total_rows"],
            "within_audit_period": period_result["within_period"],
            "excluded_outside_period": period_result["excluded"],
            "date_column_used": period_result["date_column_used"],
            "period_applied": period_result["period_applied"],
            "note": period_result.get("note", ""),
        }
        # Replace engine's DataFrame with period-filtered one
        engine.df = period_result["filtered_df"]
        logger.info(
            f"[Attribute Testing] Period filter applied: "
            f"{period_stats['total_rows_in_file']} total → "
            f"{period_stats['within_audit_period']} within period"
        )
    else:
        period_stats = {
            "total_rows_in_file": load_result["total_rows"],
            "within_audit_period": load_result["total_rows"],
            "excluded_outside_period": 0,
            "date_column_used": None,
            "period_applied": None,
            "note": "No audit period provided — all rows tested",
        }

    # ── Run all attribute tests ────────────────────────────────
    test_results = engine.run_all_attributes(test_attributes)

    # Add period stats to test results for reporting
    test_results["period_stats"] = period_stats
    test_results["column_inventory"] = column_inventory
    test_results["rows_tested"] = len(engine.df)

    # Generate audit finding
    finding = engine.generate_audit_finding(test_results, activity_name)

    return {
        "status": "success",
        "file_info": load_result,
        "column_mapping": mapping_result["mapping"],
        "column_inventory": column_inventory,
        "period_stats": period_stats,
        "test_results": test_results,
        "audit_finding": finding,
    }
