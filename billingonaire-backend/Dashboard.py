from fastapi import Depends, Query, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from collections import defaultdict
import statistics

class DashboardData:
    def __init__(self, db=None):
        self.db = db or firestore.client()

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
                raise HTTPException(status_code=400, detail="Start date must be less than or equal to end date")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        # Use filter() instead of where() with positional arguments to avoid warnings
        query = self.db.collection("daily-boards").where(
            filter=FieldFilter("board_date", ">=", start)
        ).where(
            filter=FieldFilter("board_date", "<=", end)
        )
        
        # Apply AGP filter if specified
        if agp_filter:
            query = query.where(filter=FieldFilter("respondent_lawyer", "==", agp_filter))
        docs = query.stream()
        date_counts = {}
        for doc in docs:
            d = doc.to_dict().get("board_date")
            if d:
                date_counts[d] = date_counts.get(d, 0) + 1
        return [ {"date": k, "total_matters": v} for k, v in sorted(date_counts.items()) ]

    async def get_agp_stats(self, agp_name: str = None, agp_filter=None):
        query = self.db.collection("daily-boards")
        # Use agp_filter if provided (for role-based access), otherwise use agp_name parameter
        target_agp = agp_filter or agp_name
        if target_agp:
            query = query.where(filter=FieldFilter("respondent_lawyer", "==", target_agp))
        docs = query.stream()
        agp_counts = {}
        for doc in docs:
            agp = doc.to_dict().get("respondent_lawyer")
            if agp:
                agp_counts[agp] = agp_counts.get(agp, 0) + 1
        return [ {"agp_name": k, "matters": v} for k, v in sorted(agp_counts.items(), key=lambda x: -x[1]) ]

    async def get_monthly_avg(self, year: str = None, agp_filter=None):
        query = self.db.collection("daily-boards")
        
        # Apply AGP filter if specified
        if agp_filter:
            query = query.where(filter=FieldFilter("respondent_lawyer", "==", agp_filter))
        
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
            ).where(
                filter=FieldFilter("board_date", "<=", f"{year}-12-31")
            )
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
        result = []
        for agp, months in agp_month_counts.items():
            avg = sum(months.values()) / len(months)
            result.append({"agp_name": agp, "monthly_avg": round(avg, 2)})
        return sorted(result, key=lambda x: -x["monthly_avg"])

    async def get_matters_by_date_range(self, start_date=None, end_date=None, agp_filter=None):
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
                raise HTTPException(status_code=400, detail="Start date must be less than or equal to end date")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
        
        # Query database with datetime objects (fix from previous date search issue)
        query = self.db.collection("daily-boards").where(
            filter=FieldFilter("board_date", ">=", start_dt)
        ).where(
            filter=FieldFilter("board_date", "<=", end_dt.replace(hour=23, minute=59, second=59))
        )
        
        # Apply AGP filter if specified
        if agp_filter:
            if isinstance(agp_filter, list):
                query = query.where(filter=FieldFilter("respondent_lawyer", "in", agp_filter))
            else:
                query = query.where(filter=FieldFilter("respondent_lawyer", "==", agp_filter))
        
        docs = query.stream()
        date_counts = defaultdict(int)
        
        for doc in docs:
            doc_data = doc.to_dict()
            board_date = doc_data.get("board_date")
            if board_date:
                # Convert datetime to date string for grouping
                if hasattr(board_date, 'strftime'):
                    date_str = board_date.strftime('%Y-%m-%d')
                else:
                    date_str = str(board_date)
                date_counts[date_str] += 1
        
        # Calculate average
        daily_counts = list(date_counts.values())
        average = round(statistics.mean(daily_counts), 2) if daily_counts else 0
        
        # Format response for chart visualization
        chart_data = []
        for date_str in sorted(date_counts.keys()):
            chart_data.append({
                "date": date_str,
                "total_matters": date_counts[date_str],
                "average": average  # Include average for line overlay
            })
        
        return {
            "data": chart_data,
            "summary": {
                "total_matters": sum(daily_counts),
                "average_per_day": average,
                "date_range": {"start": start, "end": end},
                "days_covered": len(daily_counts)
            }
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
            "weekly"
        )

    async def get_agp_distribution_monthly(self, agp_filter=None):
        """AGP distribution for current month to date"""
        today = datetime.today()
        month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        return await self._get_agp_distribution_for_period(
            month_start,
            today.replace(hour=23, minute=59, second=59),
            agp_filter,
            "monthly"
        )

    async def get_agp_distribution_yearly(self, agp_filter=None):
        """AGP distribution for current year to date"""
        today = datetime.today()
        year_start = today.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        
        return await self._get_agp_distribution_for_period(
            year_start,
            today.replace(hour=23, minute=59, second=59),
            agp_filter,
            "yearly"
        )

    async def _get_agp_distribution_for_period(self, start_dt, end_dt, agp_filter, period_type):
        """Helper method to get AGP distribution for a specific period"""
        query = self.db.collection("daily-boards").where(
            filter=FieldFilter("board_date", ">=", start_dt)
        ).where(
            filter=FieldFilter("board_date", "<=", end_dt)
        )
        
        # Apply AGP filter if specified
        if agp_filter:
            if isinstance(agp_filter, list):
                query = query.where(filter=FieldFilter("respondent_lawyer", "in", agp_filter))
            else:
                query = query.where(filter=FieldFilter("respondent_lawyer", "==", agp_filter))
        
        docs = query.stream()
        agp_counts = defaultdict(int)
        total_matters = 0
        
        for doc in docs:
            doc_data = doc.to_dict()
            agp = doc_data.get("respondent_lawyer")
            if agp:
                agp_counts[agp] += 1
                total_matters += 1
        
        # Calculate percentages and format response
        distribution = []
        for agp, count in sorted(agp_counts.items(), key=lambda x: -x[1]):
            percentage = round((count / total_matters * 100), 2) if total_matters > 0 else 0
            distribution.append({
                "agp_name": agp,
                "matters": count,
                "percentage": percentage
            })
        
        return {
            "period_type": period_type,
            "date_range": {
                "start": start_dt.strftime('%Y-%m-%d'),
                "end": end_dt.strftime('%Y-%m-%d')
            },
            "total_matters": total_matters,
            "distribution": distribution
        }
