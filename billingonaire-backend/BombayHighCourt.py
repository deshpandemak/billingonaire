import requests
from ecourt import ECourt, Court
import logging
from fastapi import HTTPException

class BombayHighCourt:
    def __init__(self):
        self.base_url = "https://bombayhighcourt.nic.in"
        self.ecourt = ECourt(Court(state_code='1'))

    # def configure(self):
    #     self.ecourt.configure()

    def get_case_status(self, case_type, case_number, year):
        logging.info(f"Fetching case status for case_type: {case_type}, case_number: {case_number}, year: {year}")
        try:
            # self.configure()
            case_status = self.ecourt.get_case_status(case_type=case_type, case_number=case_number, year=year)
            return case_status
        except Exception as e:
            logging.error(f"Error fetching case status: {str(e)}")
            raise HTTPException(status_code=500, detail="Error fetching case status")

    def get_case_orders(self, case_type, case_number, year):
        logging.info(f"Fetching case orders for case_type: {case_type}, case_number: {case_number}, year: {year}")
        try:
            # self.configure()
            case_orders = self.ecourt.get_case_orders(case_type=case_type, case_number=case_number, year=year)
            return case_orders
        except Exception as e:
            logging.error(f"Error fetching case orders: {str(e)}")
            raise HTTPException(status_code=500, detail="Error fetching case orders")
