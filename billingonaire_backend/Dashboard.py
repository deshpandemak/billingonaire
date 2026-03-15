import re
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import List, Optional

from fastapi import HTTPException
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter


class DashboardData:
    def __init__(self, db=None):
        self.db = db or firestore.client()

    def normalize_agp_name(self, name: str) -> str:
        """Normalize AGP name for fuzzy matching"""
        if not name:
            return ""
        # Remove common titles and prefixes
        name = re.sub(r"\b(SHRI|SMT|MS|MR|DR|ADDL|AGP|GP|BPNL)\b\.?", "", name.upper())
        # Remove extra spaces and punctuation
        name = re.sub(r"[,.\-_]", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name

    def fuzzy_match_agp_names(self, name1: str, name2: str) -> float:
        """Calculate similarity score between two AGP names"""
        norm1 = self.normalize_agp_name(name1)
        norm2 = self.normalize_agp_name(name2)

        if not norm1 or not norm2:
            return 0.0

        # Use SequenceMatcher for similarity
        return SequenceMatcher(None, norm1, norm2).ratio()

    def group_similar_agp_names(
        self, agp_counts: dict, threshold: float = 0.85
    ) -> dict:
        """Group similar AGP names together using fuzzy matching"""
        grouped = {}
        processed = set()

        for agp_name in sorted(agp_counts.keys()):
            if agp_name in processed:
                continue

            # Find all similar names
            similar_group = [agp_name]
            for other_name in agp_counts.keys():
                if other_name != agp_name and other_name not in processed:
                    similarity = self.fuzzy_match_agp_names(agp_name, other_name)
                    if similarity >= threshold:
                        similar_group.append(other_name)
                        processed.add(other_name)

            # Use the most common variant as the canonical name
            canonical_name = max(similar_group, key=lambda n: agp_counts[n])
            grouped[canonical_name] = sum(agp_counts[name] for name in similar_group)
            processed.add(agp_name)

        return grouped

    async def get_weekly_status(self, start_date=None, end_date=None, agp_filter=None):
        # Use provided dates or default to last 7 days
        today = datetime.today().date()
        week_ago = today - timedelta(days=6)
        start = start_date or week_ago.strftime("%Y-%m-%d")
        end = end_date or today.strftime("%Y-%m-%d")
        # Validate date format and range
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end, "%Y-%m-%d").date()
            if start_dt > end_dt:
                raise HTTPException(
                    status_code=400,
                    detail="Start date must be less than or equal to end date",
                )
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid date format. Use YYYY-MM-DD"
            )

        # Use filter() instead of where() with positional arguments to avoid warnings
        query = (
            self.db.collection("daily-boards")
            .where(filter=FieldFilter("board_date", ">=", start))
            .where(filter=FieldFilter("board_date", "<=", end))
        )

        # Apply AGP filter if specified
        if agp_filter:
            query = query.where(
                filter=FieldFilter("respondent_lawyer", "==", agp_filter)
            )
        docs = query.stream()
        date_counts = {}
        for doc in docs:
            d = doc.to_dict().get("board_date")
            if d:
                date_counts[d] = date_counts.get(d, 0) + 1
        return [{"date": k, "total_matters": v} for k, v in sorted(date_counts.items())]

    async def get_agp_stats(
        self, agp_name: str = None, agp_filter=None, use_fuzzy_matching: bool = True
    ):
        query = self.db.collection("daily-boards")
        # Use agp_filter if provided (for role-based access), otherwise use agp_name parameter
        target_agp = agp_filter or agp_name
        if target_agp:
            query = query.where(
                filter=FieldFilter("respondent_lawyer", "==", target_agp)
            )
        docs = query.stream()
        agp_counts = {}
        for doc in docs:
            agp = doc.to_dict().get("respondent_lawyer")
            if agp:
                agp_counts[agp] = agp_counts.get(agp, 0) + 1

        # Apply fuzzy matching to group similar names
        if use_fuzzy_matching and len(agp_counts) > 0:
            agp_counts = self.group_similar_agp_names(agp_counts, threshold=0.85)

        return [
            {"agp_name": k, "matters": v}
            for k, v in sorted(agp_counts.items(), key=lambda x: -x[1])
        ]

    async def get_monthly_avg(
        self, year: str = None, agp_filter=None, use_fuzzy_matching: bool = True
    ):
        query = self.db.collection("daily-boards")

        # Apply AGP filter if specified
        if agp_filter:
            query = query.where(
                filter=FieldFilter("respondent_lawyer", "==", agp_filter)
            )

        if year:
            # Validate year format
            try:
                year_int = int(year)
                if year_int < 1900 or year_int > datetime.now().year + 10:
                    raise HTTPException(status_code=400, detail="Invalid year range")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid year format")

            query = query.where(
                filter=FieldFilter("board_date", ">=", f"{year}-01-01")
            ).where(filter=FieldFilter("board_date", "<=", f"{year}-12-31"))
        docs = query.stream()
        agp_month_counts = {}
        for doc in docs:
            d = doc.to_dict()
            agp = d.get("respondent_lawyer")
            date = d.get("board_date")
            if agp and date:
                month = date[:7]  # YYYY-MM
                agp_month_counts.setdefault(agp, {}).setdefault(month, 0)
                agp_month_counts[agp][month] += 1

        # Apply fuzzy matching to group similar AGP names
        if use_fuzzy_matching and len(agp_month_counts) > 0:
            # First, create a mapping of canonical names
            all_agp_names = list(agp_month_counts.keys())
            name_mapping = {}
            processed = set()

            for agp_name in sorted(all_agp_names):
                if agp_name in processed:
                    continue

                similar_group = [agp_name]
                for other_name in all_agp_names:
                    if other_name != agp_name and other_name not in processed:
                        similarity = self.fuzzy_match_agp_names(agp_name, other_name)
                        if similarity >= 0.85:
                            similar_group.append(other_name)
                            processed.add(other_name)

                # Use the most common variant as canonical
                canonical_name = max(
                    similar_group, key=lambda n: sum(agp_month_counts[n].values())
                )
                for name in similar_group:
                    name_mapping[name] = canonical_name
                processed.add(agp_name)

            # Merge data using canonical names
            merged_counts = {}
            for agp, months in agp_month_counts.items():
                canonical = name_mapping.get(agp, agp)
                if canonical not in merged_counts:
                    merged_counts[canonical] = {}
                for month, count in months.items():
                    merged_counts[canonical][month] = (
                        merged_counts[canonical].get(month, 0) + count
                    )

            agp_month_counts = merged_counts

        result = []
        for agp, months in agp_month_counts.items():
            avg = sum(months.values()) / len(months)
            result.append({"agp_name": agp, "monthly_avg": round(avg, 2)})
        return sorted(result, key=lambda x: -x["monthly_avg"])

    async def get_matters_by_date_range(
        self, start_date=None, end_date=None, agp_filter=None
    ):
        """Get total matters by date with average for bar chart + line visualization"""
        # Default to last 5 days if no dates provided
        today = datetime.today().date()
        default_start = today - timedelta(days=4)  # Last 5 days including today
        start = start_date or default_start.strftime("%Y-%m-%d")
        end = end_date or today.strftime("%Y-%m-%d")

        # Validate date format and range
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d")
            end_dt = datetime.strptime(end, "%Y-%m-%d")
            if start_dt.date() > end_dt.date():
                raise HTTPException(
                    status_code=400,
                    detail="Start date must be less than or equal to end date",
                )
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid date format. Use YYYY-MM-DD"
            )

        # Query database with datetime objects (fix from previous date search issue)
        query = (
            self.db.collection("daily-boards")
            .where(filter=FieldFilter("board_date", ">=", start_dt))
            .where(
                filter=FieldFilter(
                    "board_date", "<=", end_dt.replace(hour=23, minute=59, second=59)
                )
            )
        )

        # Apply AGP filter if specified
        if agp_filter:
            if isinstance(agp_filter, list):
                query = query.where(
                    filter=FieldFilter("respondent_lawyer", "in", agp_filter)
                )
            else:
                query = query.where(
                    filter=FieldFilter("respondent_lawyer", "==", agp_filter)
                )

        docs = query.stream()
        date_counts = defaultdict(int)

        for doc in docs:
            doc_data = doc.to_dict()
            board_date = doc_data.get("board_date")
            if board_date:
                # Convert datetime to date string for grouping
                if hasattr(board_date, "strftime"):
                    date_str = board_date.strftime("%Y-%m-%d")
                else:
                    date_str = str(board_date)
                date_counts[date_str] += 1

        # Calculate average
        daily_counts = list(date_counts.values())
        average = round(statistics.mean(daily_counts), 2) if daily_counts else 0

        # Format response for chart visualization
        chart_data = []
        for date_str in sorted(date_counts.keys()):
            chart_data.append(
                {
                    "date": date_str,
                    "total_matters": date_counts[date_str],
                    "average": average,  # Include average for line overlay
                }
            )

        return {
            "data": chart_data,
            "summary": {
                "total_matters": sum(daily_counts),
                "average_per_day": average,
                "date_range": {"start": start, "end": end},
                "days_covered": len(daily_counts),
            },
        }

    async def get_agp_distribution_weekly(self, agp_filter=None):
        """AGP distribution for current week (Monday to current date)"""
        today = datetime.today()
        # Get Monday of current week
        monday = today - timedelta(days=today.weekday())
        monday_date = monday.replace(hour=0, minute=0, second=0, microsecond=0)

        return await self._get_agp_distribution_for_period(
            monday_date,
            today.replace(hour=23, minute=59, second=59),
            agp_filter,
            "weekly",
        )

    async def get_agp_distribution_monthly(self, agp_filter=None):
        """AGP distribution for current month to date"""
        today = datetime.today()
        month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        return await self._get_agp_distribution_for_period(
            month_start,
            today.replace(hour=23, minute=59, second=59),
            agp_filter,
            "monthly",
        )

    async def get_agp_distribution_yearly(self, agp_filter=None):
        """AGP distribution for current year to date"""
        today = datetime.today()
        year_start = today.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )

        return await self._get_agp_distribution_for_period(
            year_start,
            today.replace(hour=23, minute=59, second=59),
            agp_filter,
            "yearly",
        )

    async def _get_agp_distribution_for_period(
        self, start_dt, end_dt, agp_filter, period_type, use_fuzzy_matching: bool = True
    ):
        """Helper method to get AGP distribution for a specific period"""
        query = (
            self.db.collection("daily-boards")
            .where(filter=FieldFilter("board_date", ">=", start_dt))
            .where(filter=FieldFilter("board_date", "<=", end_dt))
        )

        # Apply AGP filter if specified
        if agp_filter:
            if isinstance(agp_filter, list):
                query = query.where(
                    filter=FieldFilter("respondent_lawyer", "in", agp_filter)
                )
            else:
                query = query.where(
                    filter=FieldFilter("respondent_lawyer", "==", agp_filter)
                )

        docs = query.stream()
        agp_counts = defaultdict(int)
        total_matters = 0

        for doc in docs:
            doc_data = doc.to_dict()
            agp = doc_data.get("respondent_lawyer")
            if agp:
                agp_counts[agp] += 1
                total_matters += 1

        # Apply fuzzy matching to group similar names
        if use_fuzzy_matching and len(agp_counts) > 0:
            agp_counts = self.group_similar_agp_names(agp_counts, threshold=0.85)

        # Calculate percentages and format response
        distribution = []
        for agp, count in sorted(agp_counts.items(), key=lambda x: -x[1]):
            percentage = (
                round((count / total_matters * 100), 2) if total_matters > 0 else 0
            )
            distribution.append(
                {"agp_name": agp, "matters": count, "percentage": percentage}
            )

        return {
            "period_type": period_type,
            "date_range": {
                "start": start_dt.strftime("%Y-%m-%d"),
                "end": end_dt.strftime("%Y-%m-%d"),
            },
            "total_matters": total_matters,
            "distribution": distribution,
        }

    @staticmethod
    def _parse_input_date(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"Invalid date '{value}'. Use YYYY-MM-DD"
            )

    @staticmethod
    def _to_date_str(value) -> Optional[str]:
        if value is None:
            return None
        if hasattr(value, "strftime"):
            return value.strftime("%Y-%m-%d")
        raw = str(value).strip()
        if not raw:
            return None
        if "T" in raw:
            return raw.split("T", 1)[0]
        return raw

    @staticmethod
    def _resolve_period_bounds(
        start_date: Optional[str],
        end_date: Optional[str],
        year: Optional[int],
        quarter: Optional[int],
    ):
        start_dt = DashboardData._parse_input_date(start_date)
        end_dt = DashboardData._parse_input_date(end_date)

        if quarter is not None and year is None:
            raise HTTPException(
                status_code=400, detail="year is required when quarter is provided"
            )
        if quarter is not None and quarter not in {1, 2, 3, 4}:
            raise HTTPException(status_code=400, detail="quarter must be 1, 2, 3, or 4")

        if year is not None:
            if year < 1900 or year > datetime.now().year + 10:
                raise HTTPException(status_code=400, detail="Invalid year range")

            if quarter is None:
                start_dt = datetime(year, 1, 1)
                end_dt = datetime(year, 12, 31, 23, 59, 59)
            else:
                quarter_start_month = ((quarter - 1) * 3) + 1
                start_dt = datetime(year, quarter_start_month, 1)
                if quarter == 4:
                    end_dt = datetime(year, 12, 31, 23, 59, 59)
                else:
                    end_dt = datetime(year, quarter_start_month + 3, 1) - timedelta(
                        seconds=1
                    )

        if start_dt and not end_dt:
            end_dt = start_dt.replace(hour=23, minute=59, second=59)
        if end_dt and not start_dt:
            start_dt = end_dt.replace(hour=0, minute=0, second=0)

        if start_dt and end_dt and start_dt > end_dt:
            raise HTTPException(
                status_code=400,
                detail="Start date must be less than or equal to end date",
            )

        return start_dt, end_dt

    @staticmethod
    def _matches_agp_filter(respondent_lawyer: str, agp_filter) -> bool:
        if not agp_filter:
            return True
        candidate = str(respondent_lawyer or "").strip().lower()
        if not candidate:
            return False
        if isinstance(agp_filter, list):
            allowed = {str(v or "").strip().lower() for v in agp_filter if v}
            return candidate in allowed
        return candidate == str(agp_filter).strip().lower()

    async def get_board_date_summary(
        self,
        start_date: str = None,
        end_date: str = None,
        year: int = None,
        quarter: int = None,
        limit: int = 180,
        agp_filter=None,
    ):
        """Return board-date wise case counts and basic rollups for dashboard table."""
        start_dt, end_dt = self._resolve_period_bounds(
            start_date, end_date, year, quarter
        )

        if limit < 1 or limit > 1000:
            raise HTTPException(
                status_code=400, detail="limit must be between 1 and 1000"
            )

        query = self.db.collection("daily-boards")
        if start_dt and end_dt:
            query = query.where(filter=FieldFilter("board_date", ">=", start_dt))
            query = query.where(filter=FieldFilter("board_date", "<=", end_dt))

        docs = query.stream()
        summary = {}
        total_cases = 0

        for doc in docs:
            data = doc.to_dict() or {}
            respondent_lawyer = data.get("respondent_lawyer")
            if not self._matches_agp_filter(respondent_lawyer, agp_filter):
                continue

            date_str = self._to_date_str(data.get("board_date"))
            if not date_str:
                continue

            row = summary.setdefault(
                date_str,
                {
                    "board_date": date_str,
                    "cases_count": 0,
                    "unique_respondent_lawyers": set(),
                    "unique_petitioner_lawyers": set(),
                },
            )
            row["cases_count"] += 1
            total_cases += 1

            if respondent_lawyer:
                row["unique_respondent_lawyers"].add(respondent_lawyer)

            petitioner_lawyer = data.get("petitioner_lawyer")
            if petitioner_lawyer:
                row["unique_petitioner_lawyers"].add(petitioner_lawyer)

        rows = []
        for board_date in sorted(summary.keys(), reverse=True):
            row = summary[board_date]
            rows.append(
                {
                    "board_date": board_date,
                    "cases_count": row["cases_count"],
                    "unique_respondent_lawyers": len(row["unique_respondent_lawyers"]),
                    "unique_petitioner_lawyers": len(row["unique_petitioner_lawyers"]),
                }
            )
            if len(rows) >= limit:
                break

        return {
            "rows": rows,
            "summary": {
                "total_board_dates": len(rows),
                "total_cases": total_cases,
            },
            "filters": {
                "start_date": start_dt.strftime("%Y-%m-%d") if start_dt else None,
                "end_date": end_dt.strftime("%Y-%m-%d") if end_dt else None,
                "year": year,
                "quarter": quarter,
                "limit": limit,
            },
        }

    async def get_agp_distribution_for_board_dates(
        self,
        board_dates: List[str],
        agp_filter=None,
        use_fuzzy_matching: bool = True,
    ):
        """Return AGP-wise distribution for selected board dates."""
        normalized_dates = [self._to_date_str(d) for d in (board_dates or [])]
        selected_dates = sorted({d for d in normalized_dates if d})
        if not selected_dates:
            raise HTTPException(
                status_code=400, detail="At least one board_date is required"
            )
        if len(selected_dates) > 180:
            raise HTTPException(
                status_code=400, detail="Select at most 180 board dates per request"
            )

        selected_dates_set = set(selected_dates)
        docs = self.db.collection("daily-boards").stream()
        agp_counts = defaultdict(int)
        board_breakdown = defaultdict(int)
        total_cases = 0

        for doc in docs:
            data = doc.to_dict() or {}
            date_str = self._to_date_str(data.get("board_date"))
            if date_str not in selected_dates_set:
                continue

            respondent_lawyer = data.get("respondent_lawyer")
            if not self._matches_agp_filter(respondent_lawyer, agp_filter):
                continue

            board_breakdown[date_str] += 1
            total_cases += 1
            if respondent_lawyer:
                agp_counts[respondent_lawyer] += 1

        if use_fuzzy_matching and len(agp_counts) > 0:
            agp_counts = self.group_similar_agp_names(agp_counts, threshold=0.85)

        distribution = []
        for agp_name, matters in sorted(agp_counts.items(), key=lambda x: -x[1]):
            percentage = round((matters / total_cases) * 100, 2) if total_cases else 0
            distribution.append(
                {
                    "agp_name": agp_name,
                    "matters": matters,
                    "percentage": percentage,
                }
            )

        breakdown_rows = [
            {"board_date": date_str, "cases_count": board_breakdown.get(date_str, 0)}
            for date_str in selected_dates
        ]

        return {
            "selected_dates": selected_dates,
            "total_cases": total_cases,
            "distribution": distribution,
            "board_breakdown": breakdown_rows,
        }

    async def get_cases_for_board_dates(
        self,
        board_dates: List[str],
        limit: int = 2000,
        agp_filter=None,
    ):
        """Return case rows for selected board dates to drive case-level actions in UI."""
        normalized_dates = [self._to_date_str(d) for d in (board_dates or [])]
        selected_dates = sorted({d for d in normalized_dates if d})

        if not selected_dates:
            raise HTTPException(
                status_code=400, detail="At least one board_date is required"
            )
        if limit < 1 or limit > 5000:
            raise HTTPException(
                status_code=400, detail="limit must be between 1 and 5000"
            )

        selected_dates_set = set(selected_dates)
        docs = self.db.collection("daily-boards").stream()
        cases = []

        for doc in docs:
            data = doc.to_dict() or {}
            date_str = self._to_date_str(data.get("board_date"))
            if date_str not in selected_dates_set:
                continue

            respondent_lawyer = data.get("respondent_lawyer")
            if not self._matches_agp_filter(respondent_lawyer, agp_filter):
                continue

            case_type = str(data.get("case_type") or "").strip().upper()
            case_no = str(data.get("case_no") or "").strip()
            case_year = str(data.get("case_year") or "").strip()
            case_ref = f"{case_type}/{case_no}/{case_year}"

            cases.append(
                {
                    "case_id": doc.id,
                    "case_ref": case_ref,
                    "board_date": date_str,
                    "case_type": case_type,
                    "case_no": case_no,
                    "case_year": case_year,
                    "petitioner_lawyer": data.get("petitioner_lawyer"),
                    "respondent_lawyer": respondent_lawyer,
                    "serial_number": data.get("serial_number"),
                }
            )

            if len(cases) >= limit:
                break

        cases.sort(
            key=lambda item: (item.get("board_date"), item.get("serial_number") or "")
        )

        return {
            "selected_dates": selected_dates,
            "total_cases": len(cases),
            "cases": cases,
            "limit": limit,
        }
