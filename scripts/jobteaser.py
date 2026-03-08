import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import json
import time
import urllib.parse
import logging
import os
import questionary
import re
import subprocess
import tempfile


def get_chrome_major_version():
    chrome_path = uc.find_chrome_executable()
    if not chrome_path:
        raise RuntimeError("Chrome executable not found.")

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
            cmd = ["powershell", "-NoProfile", "-Command",
                   r"(Get-Item '" + chrome_path + r"').VersionInfo.ProductVersion"]
            version_str = subprocess.check_output(cmd, text=True).strip()
        except Exception:
            version_str = None

    if not version_str:
        raise RuntimeError("Could not detect Chrome version.")

    m = re.search(r"^(\d+)\.", version_str)
    if not m:
        raise RuntimeError(f"Could not parse Chrome version: {version_str}")
    return int(m.group(1)), chrome_path


def run():
    # ── Logging ──────────────────────────────────────────────────────────────
    log_path = os.path.join(os.path.dirname(__file__), '../logs/history.log')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M'
    )

    # ── Config ────────────────────────────────────────────────────────────────
    config_path = os.path.join(os.path.dirname(__file__), '../configs/config.json')
    with open(config_path, "r", encoding="utf-16") as f:
        config = json.load(f)
    EMAIL    = config["email"]
    PASSWORD = config["jobteaser_password"]

    KEYWORD = questionary.text("Enter the job keyword:").ask()
    encoded_keyword = urllib.parse.quote_plus(KEYWORD)

    SORT_BY = "recency"
    TIME_OUT = float('inf')

    # ── URLs ──────────────────────────────────────────────────────────────────
    LOGIN_URL = (
        "https://connect.jobteaser.com/?client_id=e500827d-07fc-4766-97b4-4f960a2835e7"
        "&nonce=dcbdb1d4b01e9159c31d738e4eb687bc&organization_domain=public"
        "&redirect_uri=https%3A%2F%2Fwww.jobteaser.com%2Fusers%2Fauth%2Fconnect%2Fcallback"
        "&response_type=code&scope=openid+email+profile+groups"
        "+urn%3Aconnect%3Ajobteaser%3Acom%3Aorganization"
        "+urn%3Aconnect%3Ajobteaser%3Acom%3Aextra_attributes"
        "&state=25f41a664373a5086e61494fc4bf31d2&ui_locales=fr"
    )
    # candidacy_type=INTERNAL = "Simplified application" filter (no per-card check needed)
    BASE_SEARCH_URL = (
        f"https://www.jobteaser.com/fr/job-offers"
        f"?candidacy_type=INTERNAL&contract=cdi&location=France&q={encoded_keyword}&sort={SORT_BY}&page="
    )

    # ── Chrome ────────────────────────────────────────────────────────────────
    chrome_major, chrome_path = get_chrome_major_version()
    logging.info(f"Detected Chrome: major={chrome_major}, path={chrome_path}")

    options = uc.ChromeOptions()
    options.binary_location = chrome_path
    options.add_argument(f"--user-data-dir={tempfile.mkdtemp()}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")

    driver = uc.Chrome(version_main=chrome_major, options=options)
    wait   = WebDriverWait(driver, 10)
    driver.maximize_window()

    # ── Helpers ───────────────────────────────────────────────────────────────
    def close_cookie_popup():
        try:
            btn = WebDriverWait(driver, 4).until(
                EC.element_to_be_clickable((By.ID, "didomi-notice-agree-button")))
            btn.click()
            time.sleep(0.8)
        except Exception:
            pass

    def log(msg):
        logging.info(msg)

    # ── Counters ──────────────────────────────────────────────────────────────
    applied_count    = 0
    processed_count  = 0
    skipped_no_apply = 0
    start_time       = time.time()
    MAX_PAGES        = 50

    def print_status():
        print(
            f"\rJobs processed: {processed_count}, applied: {applied_count}",
            end="",
            flush=True
        )

    try:
        # ── Login ─────────────────────────────────────────────────────────────
        driver.get(LOGIN_URL)
        time.sleep(3)
        close_cookie_popup()

        wait.until(EC.element_to_be_clickable((By.ID, "email"))).send_keys(EMAIL)
        wait.until(EC.element_to_be_clickable((By.ID, "passwordInput"))).send_keys(PASSWORD)
        wait.until(EC.element_to_be_clickable((
            By.XPATH,
            "//button[contains(text(),'Connexion') or contains(text(),'Se connecter')]"
        ))).click()

        time.sleep(5)
        close_cookie_popup()

        driver.get(f"{BASE_SEARCH_URL}1")
        
        # Apply Sorting filter on the first page load
        try:
            # Click the sort dropdown button
            sort_btn = WebDriverWait(driver, 6).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(@class, 'ResultsSort_button')]"))
            )
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", sort_btn)
            time.sleep(0.5)
            sort_btn.click()
            time.sleep(0.5)

            # Click the appropriate sort option
            sort_label_text = "Par date" if SORT_BY == "recency" else "Par pertinence"
            sort_option = WebDriverWait(driver, 4).until(
                EC.element_to_be_clickable((By.XPATH, f"//span[contains(text(), '{sort_label_text}')]/ancestor::label"))
            )
            sort_option.click()
            time.sleep(2)  # wait for results to refresh after sorting
        except Exception as e:
            logging.warning(f"Could not apply sort filter on UI: {e}")

        wait.until(EC.presence_of_element_located(
            (By.XPATH, "//ul[contains(@class,'PageContent_results')]/li")))
        log("Login reussi — starting job loop\n")

        # ── Main loop ─────────────────────────────────────────────────────────
        visited_jobs = set()
        page = 1

        while page <= MAX_PAGES and (time.time() - start_time < TIME_OUT):
            page_url = f"{BASE_SEARCH_URL}{page}"
            driver.get(page_url)
            time.sleep(2)
            close_cookie_popup()

            # Collect ALL job links as plain strings BEFORE navigating away
            try:
                wait.until(EC.presence_of_all_elements_located(
                    (By.XPATH, "//ul[contains(@class,'PageContent_results')]/li")))
            except TimeoutException:
                break

            cards = driver.find_elements(
                By.XPATH, "//ul[contains(@class,'PageContent_results')]/li")

            if not cards:
                break

            job_links = []
            for card in cards:
                try:
                    href = card.find_element(
                        By.XPATH, ".//a[contains(@class,'JobAdCard_link')]"
                    ).get_attribute("href")
                    if href and href not in visited_jobs:
                        job_links.append(href)
                        visited_jobs.add(href)
                except NoSuchElementException:
                    pass

            if not job_links:
                page += 1
                continue

            # ── Process each job ──────────────────────────────────────────
            for idx, job_url in enumerate(job_links, 1):
                if time.time() - start_time > TIME_OUT:
                    break

                try:
                    driver.get(job_url)
                    time.sleep(2)
                    close_cookie_popup()

                    # STEP 1 — Click "Simple application" / "Candidature simplifiée"
                    try:
                        simple_btn = WebDriverWait(driver, 8).until(
                            EC.element_to_be_clickable((By.XPATH,
                                "//button["
                                "normalize-space(.)='Simple application' or "
                                "normalize-space(.)='Candidature simplifiée' or "
                                ".//span[normalize-space(text())='Simple application'] or "
                                ".//span[normalize-space(text())='Candidature simplifiée']"
                                "]"
                            ))
                        )
                        simple_btn.click()
                        time.sleep(1.5)
                    except TimeoutException:
                        skipped_no_apply += 1
                        processed_count  += 1
                        print_status()
                        continue

                    # STEP 1b — "Me connecter" (first job only)
                    try:
                        me_btn = WebDriverWait(driver, 4).until(
                            EC.element_to_be_clickable((By.XPATH,
                                "//button[normalize-space(.)='Me connecter' or "
                                "normalize-space(.)='Se connecter' or "
                                "normalize-space(.)='Connect' or "
                                "normalize-space(.)='Log in']"
                            ))
                        )
                        me_btn.click()
                        time.sleep(2)
                    except TimeoutException:
                        pass

                    # STEP 2 — Gender: click div and select Homme
                    try:
                        # Wait for gender div to appear
                        gender_div = WebDriverWait(driver, 6).until(
                            EC.presence_of_element_located((By.ID, "gender"))
                        )

                        # Natively click the div so React detects the event and opens the popover
                        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", gender_div)
                        time.sleep(0.5)
                        
                        try:
                            gender_div.click()
                        except Exception:
                            from selenium.webdriver.common.action_chains import ActionChains
                            ActionChains(driver).move_to_element(gender_div).click().perform()

                        # Wait for dropdown to be present in the DOM (it may be a React Portal)
                        homme_option = WebDriverWait(driver, 4).until(
                            EC.presence_of_element_located((By.XPATH, "//li[@data-value='GENDER_MALE']"))
                        )
                        
                        # Click Homme natively or via ActionChains
                        time.sleep(0.3)
                        try:
                            homme_option.click()
                        except Exception:
                            from selenium.webdriver.common.action_chains import ActionChains
                            ActionChains(driver).move_to_element(homme_option).click().perform()
                            
                        time.sleep(0.5)

                        # Click 'Sauvegarder les informations'
                        try:
                            save_btn = WebDriverWait(driver, 3).until(
                                EC.presence_of_element_located((By.XPATH, "//button[contains(., 'Sauvegarder')]"))
                            )
                            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", save_btn)
                            time.sleep(0.3)
                            try:
                                save_btn.click()
                            except Exception:
                                driver.execute_script("arguments[0].click();", save_btn)
                            time.sleep(1.0)
                        except TimeoutException:
                            pass

                    except TimeoutException:
                        pass
                    except Exception as ef:
                        skipped_no_apply += 1
                        processed_count  += 1
                        print_status()
                        continue

                    # STEP 2b — Motivation textarea (optional)
                    MOTIVATION = (
                        "Passionné par la cybersécurité, je souhaite mettre mes compétences "
                        "techniques au service de votre entreprise."
                    )
                    try:
                        textarea = WebDriverWait(driver, 4).until(
                            EC.presence_of_element_located((By.XPATH,
                                '//*[@id="application-flow-form"]//textarea'
                            ))
                        )
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});", textarea)
                        time.sleep(0.3)
                        textarea.clear()
                        textarea.send_keys(MOTIVATION)
                    except TimeoutException:
                        pass  # no textarea on this job

                    # STEP 3 — Final apply button
                    try:
                        apply_btn = WebDriverWait(driver, 8).until(
                            EC.element_to_be_clickable((By.XPATH,
                                "//button[@data-testid='jobad-DetailView__ApplicationFlow__Buttons__apply_button']"
                            ))
                        )
                        label3 = apply_btn.text.strip()
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});", apply_btn)
                        time.sleep(0.3)
                        driver.execute_script("arguments[0].click();", apply_btn)
                        time.sleep(2)
                        applied_count += 1
                        log(f"APPLIED ({applied_count}) '{label3}': {job_url}")
                    except TimeoutException:
                        skipped_no_apply += 1
                        logging.warning(f"No apply button: {job_url}")

                except Exception as ex:
                    skipped_no_apply += 1
                    logging.exception(f"Error on {job_url}")

                processed_count += 1
                print_status()

            page += 1
            time.sleep(1)

    except Exception as e:
        logging.exception("JobTeaser fatal error.")
        print(f"\nFatal error: {e}")

    finally:
        print()  # Add final newline
        
        logging.info(
            f"JobTeaser Session ended. Total jobs applied to: {applied_count} "
            f"(processed={processed_count})"
        )
        try:
            driver.quit()
        except Exception:
            pass