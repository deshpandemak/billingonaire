from fastapi import Depends, Query, HTTPException
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

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
