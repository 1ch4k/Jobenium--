import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json
import time
import urllib.parse
import logging
import os
import re
import subprocess
import questionary
from questionary import Choice
def get_chrome_major_version():
    chrome_path = uc.find_chrome_executable()
    if not chrome_path:
        raise RuntimeError("Chrome executable not found. Install Chrome or ensure it's discoverable.")

    version_str = None

    try:
        import winreg
        reg_paths = [
            r"SOFTWARE\Google\Chrome\BLBeacon",
            r"SOFTWARE\WOW6432Node\Google\Chrome\BLBeacon",
        ]
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for rp in reg_paths:
                try:
                    key = winreg.OpenKey(root, rp)
                    version_str, _ = winreg.QueryValueEx(key, "version")
                    winreg.CloseKey(key)
                    if version_str:
                        break
                except OSError:
                    pass
            if version_str:
                break
    except Exception:
        pass

    if not version_str:
        try:
            cmd = [
                "powershell",
                "-NoProfile",
                "-Command",
                r"(Get-Item '" + chrome_path + r"').VersionInfo.ProductVersion"
            ]
            version_str = subprocess.check_output(cmd, text=True).strip()
        except Exception:
            version_str = None

    if not version_str:
        raise RuntimeError("Could not detect Chrome version from registry or PowerShell.")

    m = re.search(r"^(\d+)\.", version_str)
    if not m:
        raise RuntimeError(f"Could not parse Chrome version from: {version_str}")

    return int(m.group(1)), chrome_path


def run():
    # ===== SETUP LOGGING =====
    log_dir = os.path.join(os.path.dirname(__file__), '../logs')
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, 'history.log')

    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M'
    )

    # ===== LOAD CONFIG =====
    config_path = os.path.join(os.path.dirname(__file__), '../configs/config.json')
    with open(config_path, "r", encoding="utf-16") as file:
        config = json.load(file)

    EMAIL = config["email"]
    PASSWORD = config["hellowork_password"]

    # ===== USER INPUT =====
    KEYWORD = questionary.text("Enter the job keyword:").ask()
    encoded_keyword = urllib.parse.quote_plus(KEYWORD)

    CITY = "France"
    encoded_city = urllib.parse.quote_plus(CITY)

    CONTRACT_TYPE_PARAMS = "&c=CDI"

    # ===== URLs =====
    LOGIN_URL = "https://www.hellowork.com/fr-fr/candidat/connexion-inscription.html#connexion"

    BASE_SEARCH_URL = (
        f"https://www.hellowork.com/fr-fr/emploi/recherche.html?"
        f"k={encoded_keyword}&k_autocomplete="
        f"&l={encoded_city}"
        f"&st=date{CONTRACT_TYPE_PARAMS}"
        f"&ray=all&d=all&p="
    )

    # ===== INIT DRIVER =====
    chrome_major, chrome_path = get_chrome_major_version()
    logging.info(f"Detected Chrome: major={chrome_major}, path={chrome_path}")

    options = uc.ChromeOptions()
    options.binary_location = chrome_path
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")

    driver = uc.Chrome(version_main=chrome_major, options=options)
    wait = WebDriverWait(driver, 15)

    applied_count = 0
    processed_count = 0
    start_time = time.time()

    def is_timed_out():
        return False  # Run infinitely until manually killed

    def safe_click(element):
        """Scroll to element then click via JavaScript."""
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", element)

    def accept_cookies():
        """Try to accept cookie banner if present."""
        try:
            btn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.ID, "hw-cc-notice-accept-btn"))
            )
            btn.click()
            time.sleep(1)
        except Exception:
            pass  # No cookie banner, continue

    try:
        # ===== LOGIN =====
        driver.get(LOGIN_URL)
        accept_cookies()

        email_input = wait.until(
            EC.presence_of_element_located((By.NAME, "email2"))
        )
        email_input.clear()
        email_input.send_keys(EMAIL)

        password_input = wait.until(
            EC.presence_of_element_located((By.NAME, "password2"))
        )
        password_input.clear()
        password_input.send_keys(PASSWORD)

        login_button = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(text(), 'Je me connecte')]")
            )
        )
        login_button.click()

        # Wait for session to be established
        time.sleep(20)
        logging.info("HelloWork session started.")
        
        # Load the search page to explicitly click the sorting filter
        page = 1
        search_url = f"{BASE_SEARCH_URL}{page}"
        driver.get(search_url)
        accept_cookies()
        time.sleep(2)

        try:
            # Click the sort button in the UI
            sortBtn = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//*[@data-cy='sortBtn']"))
            )
            safe_click(sortBtn)
            time.sleep(1)

            # Click the explicit Date radio button
            date_radio = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.ID, "date"))
            )
            safe_click(date_radio)
            time.sleep(3) # Wait for page to reload successfully with sort
            logging.info("Successfully forced UI sort to 'Par Date'.")
        except Exception as e:
            logging.warning(f"Could not apply 'Par Date' via UI, checking if it is already applied... {e}")

        # ===== SEARCH LOOP =====
        page = 1

        while not is_timed_out():
            search_url = f"{BASE_SEARCH_URL}{page}"

            try:
                driver.get(search_url)
                accept_cookies()

                job_list = wait.until(
                    EC.presence_of_all_elements_located(
                        (By.XPATH, "//ul[@aria-label='liste des offres']/li")
                    )
                )
            except Exception as e:
                logging.info(f"No jobs on page {page}, stopping.")
                break

            job_count = len(job_list)

            for i in range(job_count):
                if is_timed_out():
                    break

                try:
                    # Re-fetch the list to avoid stale element references
                    driver.get(search_url)
                    accept_cookies()

                    job_list = wait.until(
                        EC.presence_of_all_elements_located(
                            (By.XPATH, "//ul[@aria-label='liste des offres']/li")
                        )
                    )

                    if i >= len(job_list):
                        break

                    job = job_list[i]
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", job)
                    time.sleep(0.5)

                    # Get job title for logging
                    try:
                        title_el = job.find_element(By.XPATH, ".//a[@data-cy='offerTitle']")
                        job_title = title_el.text.strip()
                    except Exception:
                        job_title = f"Job #{i+1}"

                    # Click on the job title
                    job_link = job.find_element(By.XPATH, ".//a[@data-cy='offerTitle']")
                    safe_click(job_link)

                    # Wait for the job detail page to load
                    time.sleep(3)

                    current_url = driver.current_url
                    try:
                        # Find the first 'Postuler' element (anchor or text)
                        apply_button = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, "//*[@data-cy='applyButton'] | //*[contains(normalize-space(.), 'Postuler')]"))
                        )

                        # Check if this button redirects to external site
                        btn_text = apply_button.text.lower()
                        is_external = apply_button.get_attribute("data-redirect-external-url-value")
                        if is_external or "site du recruteur" in btn_text or "site de l'entreprise" in btn_text:
                            logging.warning(f"Skipping external application: {job_title} | {current_url}")
                            processed_count += 1
                            print(
                                f"\rJobs processed: {processed_count}, applied: {applied_count}",
                                end="",
                                flush=True
                            )
                            continue

                        # Click the initial postuler to reveal modal
                        safe_click(apply_button)
                        time.sleep(1)
                        
                        # Step 2: Click the 'Postuler' or 'Continuer' button within the modal
                        try:
                            submit_button = WebDriverWait(driver, 5).until(
                                EC.element_to_be_clickable((By.XPATH, "//*[@data-cy='submitButton']"))
                            )
                            safe_click(submit_button)
                            time.sleep(1)
                        except Exception:
                            # Might be a single-click apply, continue
                            pass
                            
                        # Step 3: Check for dynamically rendered application forms
                        # Sometimes it asks for just phone, sometimes up to 5 fields
                        try:
                            # Check if the form section loaded
                            WebDriverWait(driver, 3).until(
                                EC.presence_of_element_located((By.XPATH, "//*[@data-cy='sav2SubmitButton']"))
                            )
                            
                            # 1. Phone (Could be field1 or field3 based on the variant)
                            for phone_var in ["sav2_field1", "sav2_field3"]:
                                try:
                                    # Look specifically for the phone input pattern
                                    phone_input = driver.find_element(By.XPATH, f"//input[@id='{phone_var}' and @inputmode='numeric']")
                                    phone_input.clear()
                                    phone_input.send_keys("0753687016")
                                    time.sleep(0.2)
                                    break
                                except Exception:
                                    pass

                            # 2. Address
                            try:
                                addr_input = driver.find_element(By.ID, "sav2_field6")
                                addr_input.clear()
                                addr_input.send_keys("Maurepas")
                                time.sleep(0.2)
                            except Exception:
                                pass

                            # 3. Code Postal (Often field1 if field3 is phone)
                            try:
                                zip_input = driver.find_element(By.XPATH, "//input[@id='sav2_field1' and not(@inputmode='numeric')]")
                                zip_input.clear()
                                zip_input.send_keys("78310")
                                time.sleep(0.2)
                            except Exception:
                                pass

                            # 4. City
                            try:
                                city_input = driver.find_element(By.ID, "sav2_field2")
                                city_input.clear()
                                city_input.send_keys("Maurepas")
                                time.sleep(0.2)
                            except Exception:
                                pass

                            # 5. Civilité
                            try:
                                civility_select = driver.find_element(By.ID, "sav2_field4")
                                from selenium.webdriver.support.ui import Select
                                Select(civility_select).select_by_visible_text("Monsieur")
                                time.sleep(0.5)
                            except Exception:
                                pass
                            
                            # Click the final apply button associated with this form
                            final_submit = driver.find_element(By.XPATH, "//*[@data-cy='sav2SubmitButton']")
                            safe_click(final_submit)
                            time.sleep(1)
                            
                        except Exception:
                            # Dynamic info form did not appear at all
                            pass
                            
                        apply_success = True
                    except Exception:
                        # Could not find the main postuler button or click flow broke
                        pass

                    if not apply_success:
                        logging.warning(f"Apply button not found: {job_title} | {current_url}")
                        processed_count += 1
                        print(
                            f"\rJobs processed: {processed_count}, applied: {applied_count}",
                            end="",
                            flush=True
                        )
                        continue

                    # Wait for confirmation
                    time.sleep(3)

                    # Check for success confirmation message
                    confirmed = False
                    success_xpaths = [
                        "//p[contains(text(), 'Félicitations')]",
                        "//p[contains(text(), 'candidature')]",
                        "//div[contains(text(), 'Félicitations')]",
                        "//h2[contains(text(), 'envoyée')]",
                        "//*[contains(text(), 'bien été envoyée')]",
                        "//*[contains(text(), 'déjà postulé')]",
                    ]

                    for xpath in success_xpaths:
                        try:
                            driver.find_element(By.XPATH, xpath)
                            confirmed = True
                            break
                        except Exception:
                            pass

                    if confirmed:
                        applied_count += 1
                        logging.info(f"Applied: {job_title} | {current_url}")
                    else:
                        logging.warning(f"Applied but no confirmation: {job_title} | {current_url}")

                    processed_count += 1
                    print(
                        f"\rJobs processed: {processed_count}, applied: {applied_count}",
                        end="",
                        flush=True
                    )

                    time.sleep(2)

                except Exception as e:
                    logging.error(f"Error processing job #{i+1} on page {page}: {e}")
                    processed_count += 1
                    print(
                        f"\rJobs processed: {processed_count}, applied: {applied_count}",
                        end="",
                        flush=True
                    )
                    time.sleep(1)
                    continue

            page += 1
            time.sleep(2)

    except Exception as e:
        logging.error(f"Fatal error: {e}")

    finally:
        print()  # Just to newline after the last \r print
        elapsed = int(time.time() - start_time)
        logging.info(
            f"HelloWork Session ended. Total jobs applied to: {applied_count} "
            f"(processed={processed_count})"
        )
        driver.quit()


if __name__ == "__main__":
    run()