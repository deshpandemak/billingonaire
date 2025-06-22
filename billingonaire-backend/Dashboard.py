from fastapi import APIRouter
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta

class DashboardData:
    def __init__(self, db=None):
        from firebase_admin import firestore
        self.db = db or firestore.client()

    async def get_weekly_status(self):
        today = datetime.today().date()
        week_ago = today - timedelta(days=6)
        docs = self.db.collection("daily-boards").where("board_date", ">=", week_ago.strftime("%Y-%m-%d")).stream()
        date_counts = {}
        for doc in docs:
            d = doc.to_dict().get("board_date")
            if d:
                date_counts[d] = date_counts.get(d, 0) + 1
        return [ {"date": k, "total_matters": v} for k, v in sorted(date_counts.items()) ]

    async def get_agp_stats(self):
        docs = self.db.collection("daily-boards").stream()
        agp_counts = {}
        for doc in docs:
            agp = doc.to_dict().get("respondent_lawyer")
            if agp:
                agp_counts[agp] = agp_counts.get(agp, 0) + 1
        return [ {"agp_name": k, "matters": v} for k, v in sorted(agp_counts.items(), key=lambda x: -x[1]) ]

    async def get_monthly_avg(self):
        docs = self.db.collection("daily-boards").stream()
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

router = APIRouter()
dashboard_data = DashboardData()

@router.get("/dashboard/weekly-status")
async def dashboard_weekly_status():
    data = await dashboard_data.get_weekly_status()
    return JSONResponse(content=data)

@router.get("/dashboard/agp-stats")
async def dashboard_agp_stats():
    data = await dashboard_data.get_agp_stats()
    return JSONResponse(content=data)

@router.get("/dashboard/monthly-avg")
async def dashboard_monthly_avg():
    data = await dashboard_data.get_monthly_avg()
    return JSONResponse(content=data)
