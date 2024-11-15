import requests

class BombayHighCourt:
    def __init__(self):
        self.base_url = "https://bombayhighcourt.nic.in"

    def get_case_status(self, case_number):
        url = f"{self.base_url}/case_status/{case_number}"
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        else:
            response.raise_for_status()

    def get_case_orders(self, case_number):
        url = f"{self.base_url}/case_orders/{case_number}"
        response = requests.get(url)
        if response.status_code == 200:
            return response.json()
        else:
            response.raise_for_status()
