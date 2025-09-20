import time
import logging
from typing import Dict, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import base64
import os

class CaptchaAutomationError(Exception):
    """Custom exception for CAPTCHA automation errors"""
    pass

class BombayCaptchaAutomator:
    """
    Automated CAPTCHA solving for Bombay High Court website
    Uses browser automation to fill forms and attempt CAPTCHA solving
    """
    
    def __init__(self):
        self.driver = None
        self.wait_timeout = 30
        self.setup_driver()
        
    def setup_driver(self):
        """Setup Chrome driver with appropriate options"""
        try:
            chrome_options = Options()
            chrome_options.add_argument('--headless')  # Run in background
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
            
            self.driver = webdriver.Chrome(options=chrome_options)
            self.wait = WebDriverWait(self.driver, self.wait_timeout)
            
            logging.info("Chrome driver initialized successfully")
            
        except Exception as e:
            logging.error(f"Failed to setup Chrome driver: {e}")
            raise CaptchaAutomationError(f"Driver setup failed: {e}")
    
    def navigate_to_case_search(self, court_code: str = "2") -> bool:
        """Navigate to the court case search page"""
        try:
            search_url = f"https://hcservices.ecourts.gov.in/ecourtindiaHC/cases/case_no.php?state_cd=1&dist_cd=1&court_code={court_code}&stateNm=Bombay"
            
            logging.info(f"Navigating to case search: {search_url}")
            self.driver.get(search_url)
            
            # Wait for the page to load
            self.wait.until(EC.presence_of_element_located((By.NAME, "case_no")))
            
            logging.info("Successfully navigated to case search page")
            return True
            
        except Exception as e:
            logging.error(f"Failed to navigate to case search: {e}")
            return False
    
    def fill_case_form(self, case_type: str, case_number: str, case_year: str) -> bool:
        """Fill the case search form with the provided details"""
        try:
            # Fill case type dropdown
            case_type_select = Select(self.driver.find_element(By.NAME, "case_type"))
            case_type_select.select_by_value(case_type)
            
            # Fill case number
            case_no_input = self.driver.find_element(By.NAME, "case_no")
            case_no_input.clear()
            case_no_input.send_keys(case_number)
            
            # Fill case year
            case_year_select = Select(self.driver.find_element(By.NAME, "case_year"))
            case_year_select.select_by_value(case_year)
            
            logging.info(f"Form filled: {case_type}/{case_number}/{case_year}")
            return True
            
        except Exception as e:
            logging.error(f"Failed to fill case form: {e}")
            return False
    
    def get_captcha_image(self) -> Optional[str]:
        """Extract CAPTCHA image as base64 string"""
        try:
            # Find CAPTCHA image element
            captcha_img = self.driver.find_element(By.XPATH, "//img[contains(@src, 'securimage_show.php')]")
            
            # Get image as base64
            captcha_base64 = self.driver.execute_script("""
                var canvas = document.createElement('canvas');
                var ctx = canvas.getContext('2d');
                var img = arguments[0];
                canvas.width = img.width;
                canvas.height = img.height;
                ctx.drawImage(img, 0, 0);
                return canvas.toDataURL('image/png').substring(22);
            """, captcha_img)
            
            logging.info("CAPTCHA image extracted successfully")
            return captcha_base64
            
        except Exception as e:
            logging.error(f"Failed to extract CAPTCHA image: {e}")
            return None
    
    def solve_captcha_manual_mode(self) -> Dict:
        """
        Manual CAPTCHA solving mode - returns CAPTCHA image for human solving
        """
        try:
            captcha_image = self.get_captcha_image()
            
            if not captcha_image:
                return {"error": "Failed to extract CAPTCHA image"}
            
            return {
                "status": "manual_solving_required",
                "captcha_image": captcha_image,
                "message": "Please solve the CAPTCHA manually",
                "instructions": "Enter the CAPTCHA text and submit"
            }
            
        except Exception as e:
            logging.error(f"Manual CAPTCHA mode failed: {e}")
            return {"error": str(e)}
    
    def submit_captcha(self, captcha_text: str) -> Dict:
        """Submit the form with solved CAPTCHA"""
        try:
            # Find CAPTCHA input field
            captcha_input = self.driver.find_element(By.NAME, "cap_val")
            captcha_input.clear()
            captcha_input.send_keys(captcha_text)
            
            # Submit the form
            submit_button = self.driver.find_element(By.NAME, "btn_case_no")
            submit_button.click()
            
            # Wait for results or error
            time.sleep(3)
            
            # Check if we got results or an error
            try:
                # Look for case details table
                results_table = self.driver.find_element(By.XPATH, "//table[contains(@class, 'table') or contains(@border, '1')]")
                
                if results_table:
                    case_details = self.extract_case_details()
                    return {
                        "status": "success",
                        "case_details": case_details,
                        "message": "Case details retrieved successfully"
                    }
                    
            except NoSuchElementException:
                # Check for error message
                try:
                    error_msg = self.driver.find_element(By.XPATH, "//*[contains(text(), 'Invalid') or contains(text(), 'Error')]")
                    return {
                        "status": "captcha_failed",
                        "message": f"CAPTCHA verification failed: {error_msg.text}"
                    }
                except NoSuchElementException:
                    return {
                        "status": "no_results",
                        "message": "No case found with the provided details"
                    }
            
        except Exception as e:
            logging.error(f"Failed to submit CAPTCHA: {e}")
            return {"error": str(e)}
    
    def extract_case_details(self) -> Dict:
        """Extract case details from the results page"""
        try:
            case_details = {}
            
            # Look for case information table
            tables = self.driver.find_elements(By.TAG_NAME, "table")
            
            for table in tables:
                rows = table.find_elements(By.TAG_NAME, "tr")
                
                for row in rows:
                    cells = row.find_elements(By.TAG_NAME, "td")
                    
                    if len(cells) >= 2:
                        header = cells[0].text.strip().lower()
                        value = cells[1].text.strip()
                        
                        if 'petitioner' in header:
                            case_details['petitioner'] = value
                        elif 'respondent' in header:
                            case_details['respondent'] = value
                        elif 'status' in header:
                            case_details['status'] = value
                        elif 'next' in header and 'date' in header:
                            case_details['next_date'] = value
                        elif 'stage' in header:
                            case_details['stage'] = value
            
            # Try to extract order links
            order_links = []
            links = self.driver.find_elements(By.XPATH, "//a[contains(@href, 'order') or contains(@href, 'Order')]")
            
            for link in links:
                order_links.append({
                    "text": link.text,
                    "url": link.get_attribute("href")
                })
            
            if order_links:
                case_details['order_links'] = order_links
            
            return case_details
            
        except Exception as e:
            logging.error(f"Failed to extract case details: {e}")
            return {"extraction_error": str(e)}
    
    def automated_case_lookup(self, case_ref: str, court_code: str = "2") -> Dict:
        """
        Perform automated case lookup with manual CAPTCHA solving step
        Returns CAPTCHA image for human solving
        """
        try:
            # Parse case reference
            parts = case_ref.strip().upper().split('/')
            if len(parts) != 3:
                return {"error": "Invalid case reference format. Expected: TYPE/NUMBER/YEAR"}
            
            case_type, case_number, case_year = parts
            
            # Navigate to search page
            if not self.navigate_to_case_search(court_code):
                return {"error": "Failed to navigate to case search page"}
            
            # Fill the form
            if not self.fill_case_form(case_type, case_number, case_year):
                return {"error": "Failed to fill case form"}
            
            # Get CAPTCHA for manual solving
            return self.solve_captcha_manual_mode()
            
        except Exception as e:
            logging.error(f"Automated case lookup failed: {e}")
            return {"error": str(e)}
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up browser resources"""
        try:
            if self.driver:
                self.driver.quit()
                logging.info("Browser driver cleaned up")
        except Exception as e:
            logging.error(f"Cleanup failed: {e}")

# Factory function for creating automator instances
def create_captcha_automator() -> BombayCaptchaAutomator:
    """Create a new CAPTCHA automator instance"""
    try:
        return BombayCaptchaAutomator()
    except Exception as e:
        logging.error(f"Failed to create CAPTCHA automator: {e}")
        raise