import requests
from ecourts import ECourt

class BombayHighCourt:
    def __init__(self):
        self.base_url = "https://bombayhighcourt.nic.in"
        self.ecourt = ECourt()

    def configure(self):
        self.ecourt.configure(court="Bombay High Court")

    def get_case_status(self, case_type, case_number, year):
        self.configure()
        case_status = self.ecourt.get_case_status(case_type=case_type, case_number=case_number, year=year)
        return case_status

    def get_case_orders(self, case_type, case_number, year):
        self.configure()
        case_orders = self.ecourt.get_case_orders(case_type=case_type, case_number=case_number, year=year)
        return case_orders
