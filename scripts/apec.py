# scripts/apec.py
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import json
import time
import urllib.parse
import logging
import os
import questionary
import re
import subprocess


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


def dismiss_google_translate_bar(driver):
    try:
        driver.execute_script("""
            let f = document.querySelector('iframe.goog-te-banner-frame');
            if (f) { f.style.display = 'none'; }
            document.body.style.top = '0px';
        """)
    except Exception:
        pass


def accept_cookies(driver):
    xpaths = [
        "//*[@id='onetrust-accept-btn-handler']",
        "//button[contains(., 'Autoriser tous les cookies')]",
        "//button[contains(., 'Tout accepter')]",
        "//button[contains(., 'Accepter')]",
    ]
    for xp in xpaths:
        try:
            btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, xp)))
            btn.click()
            return True
        except Exception:
            pass
    return False


def find_apply_button(driver, wait):
    """
    On offer detail page, there is a yellow button:
      - "Postuler" (internal easy apply)  ✅ we want this
      - "Postuler sur le site de l'entreprise" (external) ❌ skip
    This returns (element, normalized_text) or (None, "")
    """
    candidates = [
        "//button[contains(., 'Postuler')]",
        "//a[contains(., 'Postuler')]",
        "//*[self::button or self::a][contains(@class,'btn') and contains(., 'Postuler')]",
    ]
    for xp in candidates:
        try:
            el = wait.until(EC.presence_of_element_located((By.XPATH, xp)))
            txt = (el.text or "").strip()
            if txt:
                return el, txt
        except Exception:
            pass
    return None, ""


def click_js(driver, element):
    driver.execute_script("arguments[0].click();", element)


def wait_offer_detail_loaded(wait):
    wait.until(EC.presence_of_element_located((By.XPATH, "//*[contains(.,'Offre suivante') or contains(.,'Ref. Apec')]")))


def run():
    log_path = os.path.join(os.path.dirname(__file__), "../logs/history.log")
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M"
    )

    config_path = os.path.join(os.path.dirname(__file__), "../configs/config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    EMAIL = config["email"]
    PASSWORD = config["apec_password"]

    KEYWORD = questionary.text("Enter the job keyword:").ask()
    encoded_keyword = urllib.parse.quote_plus(KEYWORD)

    CONTRACT_TYPE = "101888"  # CDI
    SORT_BY = "DATE"
    TIME_OUT = float('inf')

    LOGIN_URL = "https://www.apec.fr/"
    BASE_SEARCH_URL = (
        "https://www.apec.fr/candidat/recherche-emploi.html/emploi"
        "?typesConvention=143684&typesConvention=143685&typesConvention=143686"
        "&typesConvention=143687&typesConvention=143706"
        f"&motsCles={encoded_keyword}"
        f"&typesContrat={CONTRACT_TYPE}"
        "&niveauxExperience=101881"
        f"&sortsType={SORT_BY}"
        "&page="
    )

    chrome_major, chrome_path = get_chrome_major_version()
    logging.info(f"Detected Chrome: major={chrome_major}, path={chrome_path}")

    options = uc.ChromeOptions()
    options.binary_location = chrome_path

    import tempfile
    options.add_argument(f"--user-data-dir={tempfile.mkdtemp()}")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")

    driver = uc.Chrome(version_main=chrome_major, options=options)
    wait = WebDriverWait(driver, 12)
    driver.maximize_window()

    applied_count = 0
    processed_count = 0
    skipped_external = 0
    skipped_no_apply = 0
    start_time = time.time()

    try:
        try:
            driver.get(LOGIN_URL)
            time.sleep(1)

            dismiss_google_translate_bar(driver)
            accept_cookies(driver)
            dismiss_google_translate_bar(driver)

            login_popup = wait.until(
                EC.element_to_be_clickable((By.XPATH, "//a[contains(@onclick,'showloginPopin')]"))
            )
            click_js(driver, login_popup)

            email_input = wait.until(EC.presence_of_element_located((By.NAME, "emailid")))
            email_input.clear()
            email_input.send_keys(EMAIL)

            password_input = wait.until(EC.presence_of_element_located((By.NAME, "password")))
            password_input.clear()
            password_input.send_keys(PASSWORD)

            login_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Se connecter')]")))
            click_js(driver, login_button)

            time.sleep(3)
            logging.info("APEC Session started.")
        except Exception as e:
            logging.exception("APEC login failed.")
            print("APEC login failed:", repr(e))
            try:
                driver.quit()
            except Exception:
                pass
            return


        page = 0
        while True:
            if time.time() - start_time > TIME_OUT:
                break

            try:
                driver.get(f"{BASE_SEARCH_URL}{page}")
                dismiss_google_translate_bar(driver)

                job_list = wait.until(
                    EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@class,'container-result')]/div"))
                )
            except Exception:
                break

            for i in range(len(job_list)):
                if time.time() - start_time > TIME_OUT:
                    break

                try:
                    job_list = wait.until(
                        EC.presence_of_all_elements_located((By.XPATH, "//div[contains(@class,'container-result')]/div"))
                    )
                    job = job_list[i]

                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", job)
                    time.sleep(0.2)

                    job_link = job.find_element(By.XPATH, ".//a[@queryparamshandling='merge']")
                    click_js(driver, job_link)

                    wait_offer_detail_loaded(wait)
                    dismiss_google_translate_bar(driver)

                    # find apply button
                    apply_btn, apply_text = find_apply_button(driver, wait)
                    if not apply_btn:
                        skipped_no_apply += 1
                    else:
                        t = apply_text.strip().lower()

                        if "postuler sur le site" in t or "site de l'entreprise" in t or "site de l’entreprise" in t:
                            skipped_external += 1
                        elif t == "postuler":
                            click_js(driver, apply_btn)
                            time.sleep(1)

                            try:
                                btn2 = WebDriverWait(driver, 6).until(
                                    EC.element_to_be_clickable((By.XPATH, "//button[contains(.,'Postuler')]"))
                                )
                                click_js(driver, btn2)
                                time.sleep(0.8)
                            except TimeoutException:
                                pass

                            try:
                                btn3 = WebDriverWait(driver, 6).until(
                                    EC.element_to_be_clickable((
                                        By.XPATH,
                                        "//button[contains(.,'Envoyer') and (contains(.,'candidature') or contains(.,'ma candidature'))]"
                                    ))
                                )
                                click_js(driver, btn3)
                                applied_count += 1
                                time.sleep(0.8)
                            except TimeoutException:
                                pass
                        else:
                            skipped_no_apply += 1

                    processed_count += 1
                    print(
                        f"\rJobs processed: {processed_count}, applied: {applied_count}",
                        end="",
                        flush=True
                    )

                    driver.get(f"{BASE_SEARCH_URL}{page}")
                    dismiss_google_translate_bar(driver)
                    time.sleep(0.6)

                except Exception:
                    processed_count += 1
                    print(
                        f"\rJobs processed: {processed_count}, applied: {applied_count}",
                        end="",
                        flush=True
                    )
                    try:
                        driver.get(f"{BASE_SEARCH_URL}{page}")
                        dismiss_google_translate_bar(driver)
                    except Exception:
                        pass
                    time.sleep(0.6)
                    continue

            page += 1
            time.sleep(1.5)

    except Exception:
        logging.exception("APEC error occurred.")
        print("\nAn error occurred.")
    finally:
        try:
            logging.info(
                f"APEC Session ended. Total jobs applied to: {applied_count} "
                f"(processed={processed_count})"
            )
        except Exception:
            pass

        try:
            driver.quit()
        except Exception:
            pass
        driver = None