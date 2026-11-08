"""
Amizone faculty-feedback helper.

You log in and solve the CAPTCHA yourself in the browser window this opens.
The script then walks the "My Faculty" list, selects "Yes" / "Strongly Agree"
on each feedback form, shows you every answer, and submits.

Anything that is not a clear Yes / Strongly Agree is left for you to decide.
Read the questions it prints. You are responsible for what you submit.

Run `python main.py --help` for options. See README.md for setup.
"""

import argparse
import logging
import os
import platform
import re
import subprocess
import sys
import time

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import (
        TimeoutException,
        StaleElementReferenceException,
    )
except ImportError as _e:  # friendlier than a raw traceback for first-time users
    sys.exit(
        f"Missing dependency ({_e.name}). Install the requirements first:\n"
        "    pip install -r requirements.txt\n"
        "or run run.bat (Windows) / ./run.sh (macOS, Linux), which does it for you."
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("feedback")

LOGIN_URL = "https://s.amizone.net"
LOGIN_TIMEOUT = 180

# Words in a popup that suggest the portal rejected something. Such popups are
# logged and make the submit count as failed instead of being silently closed.
DEFAULT_COMMENT = ""
AUTO_SUBMIT = True  # submit without asking when every answer is Yes / Strongly Agree
ERROR_WORDS = ("error", "fail", "required", "please", "invalid", "not submitted",
               "unable", "mandatory", "select")
popup_errors = []

FAST_SELECT_JS = r"""
const done = arguments[arguments.length - 1];
const delayMs = arguments[0] * 1000;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
const inSmallDialog = r => {
  const d = r.closest(".modal, [role='dialog'], [role='alertdialog']");
  return d && d.querySelectorAll("input[type='radio']").length < 4;
};
const radios = Array.from(document.querySelectorAll("input[type='radio']")).filter(r => !inSmallDialog(r));

// Only trust text that belongs to this one radio. The old fallback read the
// whole parent, which can hold every option and match all of them.
const labelText = r => {
  const l = r.closest('label') || (r.id && document.querySelector(`label[for="${r.id}"]`));
  if (l) return norm(l.textContent);
  const p = r.parentElement;
  if (p && p.querySelectorAll("input[type='radio']").length === 1) return norm(p.textContent);
  let t = '', n = r.nextSibling;
  while (n && !(n.nodeType === 1 && n.matches("input[type='radio']"))) {
    t += n.textContent || ''; n = n.nextSibling;
  }
  return norm(t);
};

const questionText = rs => {
  let el = rs[0].parentElement;
  while (el && !rs.every(r => el.contains(r))) el = el.parentElement;
  while (el && el.querySelectorAll("input[type='radio']").length === rs.length && el.parentElement &&
         el.parentElement.querySelectorAll("input[type='radio']").length === rs.length) el = el.parentElement;
  let t = norm(el ? el.textContent : '');
  rs.forEach(r => { const lt = labelText(r); if (lt) t = t.split(lt).join(' '); });
  return t.replace(/\s+/g, ' ').trim().slice(0, 140);
};

(async () => {
  const groups = {};
  radios.forEach(r => { if (r.name) (groups[r.name] ||= []).push(r); });
  let clicked = 0;
  for (const rs of Object.values(groups)) {
    const pick = rs.find(r => { const t = labelText(r); return t.includes('strongly agree') || /^yes\b/.test(t); })
      || rs.find(r => /^(yes|true|y)$/i.test((r.value || '').trim()));
    if (!pick || pick.checked) continue;
    pick.click();
    if (!pick.checked) {
      rs.forEach(r => { r.checked = (r === pick); });
      pick.dispatchEvent(new Event('click', {bubbles: true}));
    }
    pick.dispatchEvent(new Event('change', {bubbles: true}));
    clicked++;
    await sleep(delayMs);
  }
  const unanswered = [], summary = [];
  for (const [name, rs] of Object.entries(groups)) {
    const c = rs.find(r => r.checked);
    if (!c) unanswered.push(name);
    const a = c ? (labelText(c) || String(c.value).toLowerCase()) : '(none)';
    const ok = a.includes('strongly agree') || /^(yes|true|y)\b/.test(a);
    const row = rs[0].closest('tr, li, div');
    summary.push({q: questionText(rs), a,
      dbg: ok ? '' : rs.map(r => `[id=${r.id} value=${r.value} label=${labelText(r)} checked=${r.checked}]`).join(' ')
           + ' ROW: ' + (row ? row.outerHTML.replace(/\s+/g, ' ').slice(0, 700) : '')});
  }
  done({clicked, unanswered, summary});
})();
"""

VISIBLE_POPUPS_JS = r"""
const vis = e => {
  const r = e.getBoundingClientRect();
  const s = getComputedStyle(e);
  return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
};
const sel = ".modal, [role='dialog'], [role='alertdialog'], .swal2-popup, .bootbox, .ui-dialog";
return Array.from(document.querySelectorAll(sel))
  .filter(vis)
  .filter(e => !e.querySelector("textarea") && e.querySelectorAll("input[type='radio']").length < 4);
"""

DISMISS_TEXTS = ("ok", "got it", "dismiss", "close", "continue", "done", "no thanks")
POPUP_BUTTONS_XPATH = (
    ".//button | .//input[@type='button' or @type='submit'] "
    "| .//a[contains(@class,'btn')] | .//*[@data-dismiss] | .//*[contains(@class,'close')]"
)

SUBMIT_XPATHS = [
    "//input[@id='btnSubmit']",
    "//input[@type='submit' and @value='Submit']",
    "//button[@type='submit']",
    "//button[contains(text(),'Submit')]",
]

COMMENT_XPATHS = [
    "//textarea[@id='FeedbackRating_Comments']",
    "//textarea[@name='FeedbackRating_Comments']",
    "//textarea",
]


uc.Chrome.__del__ = lambda self: None


def detect_chrome_major():
    """Return the installed Google Chrome major version (int) or None.

    undetected_chromedriver downloads a driver for the *newest* Chrome by default.
    If your Chrome is older, you get "This version of ChromeDriver only supports
    Chrome version X". Telling it the real major version avoids that.
    """
    system = platform.system()
    commands = []
    if system == "Windows":
        for hive in ("HKCU", "HKLM"):
            commands.append(["reg", "query", rf"{hive}\Software\Google\Chrome\BLBeacon", "/v", "version"])
        for root_env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(root_env)
            if base:
                exe = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
                if os.path.exists(exe):
                    commands.append(
                        ["powershell", "-NoProfile", "-Command", f"(Get-Item '{exe}').VersionInfo.ProductVersion"]
                    )
    elif system == "Darwin":
        commands.append(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--version"])
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            commands.append([name, "--version"])

    for cmd in commands:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        m = re.search(r"(\d+)\.\d+\.\d+\.\d+", out)
        if m:
            return int(m.group(1))
    return None


def make_driver(chrome_version=None):
    def build(version_main):
        # ChromeOptions objects cannot be reused across Chrome() calls, so build fresh.
        options = uc.ChromeOptions()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-save-password-bubble")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--no-first-run")
        options.add_experimental_option(
            "prefs",
            {
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
                "profile.password_manager_leak_detection": False,
                "autofill.profile_enabled": False,
                "autofill.credit_card_enabled": False,
            },
        )
        return uc.Chrome(options=options, version_main=version_main)

    version = chrome_version or detect_chrome_major()
    if version:
        log.info("Using Chrome major version %s", version)
    else:
        log.info("Could not detect Chrome version; letting undetected_chromedriver choose.")
    try:
        return build(version)
    except Exception as e:
        # Typical message: "This version of ChromeDriver only supports Chrome version 140
        #                   Current browser version is 138.0.7204.101"
        m = re.search(r"Current browser version is (\d+)", str(e))
        if m and int(m.group(1)) != version:
            log.warning("Driver/Chrome mismatch; retrying with Chrome %s", m.group(1))
            return build(int(m.group(1)))
        raise


def _visible_popups(driver):
    try:
        return driver.execute_script(VISIBLE_POPUPS_JS) or []
    except Exception as e:
        log.debug("popup scan failed: %s", e)
        return []


def _pick_dismiss_button(popup):
    fallback = None
    for b in popup.find_elements(By.XPATH, POPUP_BUTTONS_XPATH):
        try:
            if not b.is_displayed():
                continue
            label = (b.text or b.get_attribute("value") or "").strip().lower()
            cls = (b.get_attribute("class") or "").lower()
        except StaleElementReferenceException:
            continue
        if label in DISMISS_TEXTS:
            return b
        if b.get_attribute("data-dismiss") or "close" in cls:
            fallback = fallback or b
    return fallback


def _is_gone(el):
    try:
        return not el.is_displayed()
    except StaleElementReferenceException:
        return True


def handle_popups(driver, timeout=5.0, quiet=0.0):
    deadline = time.time() + timeout
    quiet_since = None
    closed = 0
    while time.time() < deadline:
        try:
            driver.switch_to.alert.accept()
            closed += 1
            continue
        except Exception:
            pass

        popups = _visible_popups(driver)
        if not popups:
            if quiet <= 0:
                break
            quiet_since = quiet_since or time.time()
            if time.time() - quiet_since >= quiet:
                break
            time.sleep(0.1)
            continue

        quiet_since = None
        popup = popups[-1]
        try:
            ptxt = " ".join((popup.text or "").split())
        except Exception:
            ptxt = ""
        if ptxt:
            log.info("Popup text: %s", ptxt[:200])
            if any(w in ptxt.lower() for w in ERROR_WORDS):
                popup_errors.append(ptxt[:200])
        btn = _pick_dismiss_button(popup)
        try:
            if btn is not None:
                click_element(driver, btn)
            else:
                popup.send_keys(Keys.ESCAPE)
            closed += 1
        except Exception as e:
            log.debug("popup dismiss failed: %s", e)
        try:
            WebDriverWait(driver, 2, poll_frequency=0.1).until(
                lambda d: _is_gone(popup)
            )
        except TimeoutException:
            log.debug("popup still visible after dismiss")
            time.sleep(0.2)
    if closed:
        log.info("Closed %d popup(s)", closed)
    return closed


def click_element(driver, el):
    try:
        el.click()
        return True
    except Exception as e:
        log.debug("native click failed: %s", e)
    try:
        driver.execute_script("arguments[0].click();", el)
        return True
    except Exception as e:
        log.warning("js click failed: %s", e)
        return False


def get_feedback_button(driver):
    els = driver.find_elements(
        By.XPATH,
        "//a[contains(@class,'btn') and contains(.,'Feedback') and not(contains(.,'Post Message'))]",
    )
    for el in els:
        try:
            if el.is_displayed():
                return el
        except StaleElementReferenceException:
            continue
    return None


SELECTION_DELAY = 0.5


def fill_options(driver):
    driver.set_script_timeout(120)
    result = driver.execute_async_script(FAST_SELECT_JS, SELECTION_DELAY)
    log.info("Selected %d options", result["clicked"])
    if result["unanswered"]:
        log.warning(
            "Unanswered question groups (no matching label, answer manually): %s",
            ", ".join(result["unanswered"]),
        )
    return result


def add_comment(driver, text):
    for sel in COMMENT_XPATHS:
        for ta in driver.find_elements(By.XPATH, sel):
            try:
                if ta.is_displayed():
                    ta.clear()
                    if text:
                        ta.send_keys(text)
                    return True
            except StaleElementReferenceException:
                continue
    log.warning("No comment box found")
    return False


def ask(prompt):
    try:
        return input(prompt).strip()
    except EOFError:
        return "n"


def element_gone(el):
    try:
        return not el.is_displayed()
    except StaleElementReferenceException:
        return True


def submit_and_wait(driver):
    popup_errors.clear()
    for sel in SUBMIT_XPATHS:
        for btn in driver.find_elements(By.XPATH, sel):
            try:
                visible = btn.is_displayed()
            except StaleElementReferenceException:
                continue
            if not visible:
                continue
            if not click_element(driver, btn):
                continue
            try:
                WebDriverWait(driver, 15).until(lambda d: element_gone(btn))
            except TimeoutException:
                log.warning("Submit button still visible after 15s")
                return False
            handle_popups(driver, quiet=0.8)
            if popup_errors:
                log.error("Portal showed a possible error after submit: %s", popup_errors[-1])
                return False
            return True
    log.warning("No submit button found")
    return False


def wait_for_login(driver):
    driver.get(LOGIN_URL)
    log.info("Log in and solve the CAPTCHA. Waiting up to %ds...", LOGIN_TIMEOUT)
    try:
        WebDriverWait(driver, LOGIN_TIMEOUT).until(
            lambda d: "/Home" in d.current_url or "dashboard" in d.current_url.lower()
        )
    except TimeoutException:
        raise RuntimeError("Login not detected within the timeout")
    log.info("Logged in.")
    handle_popups(driver, quiet=1.5)


MY_FACULTY_XPATHS = [
    "//a[normalize-space(.)='My Faculty']",
    "//a[contains(normalize-space(.),'My Faculty')]",
    "//*[self::span or self::li][normalize-space(.)='My Faculty']",
]


def open_my_faculty(driver):
    for sel in MY_FACULTY_XPATHS:
        try:
            el = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, sel))
            )
        except TimeoutException:
            continue
        if click_element(driver, el):
            log.info("Opened My Faculty.")
            return True
    log.warning("Could not find 'My Faculty' in the menu. Click it manually.")
    return False


def process_feedback(driver, btn):
    handle_popups(driver)
    if not click_element(driver, btn):
        log.warning("Could not click Feedback button")
        return False
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='radio']"))
        )
    except TimeoutException:
        log.warning("Feedback form did not load")
        return False
    handle_popups(driver, quiet=1.0)
    result = None
    for _ in range(10):
        result = fill_options(driver)
        if len(result["summary"]) >= 3:
            break
        log.info("Form questions not loaded yet, waiting...")
        time.sleep(1.5)
        handle_popups(driver, quiet=0.5)
    if len(result["summary"]) < 3:
        log.error("Could not find the feedback questions on the page. Not submitting.")
        return False

    print("\n--- Answers selected (read the questions!) ---")
    for i, s in enumerate(result["summary"], 1):
        print(f"{i:2}. {s['q'] or '(question text not found)'}\n      -> {s['a']}")
        if s.get("dbg"):
            print("      DEBUG:", s["dbg"])
    if result["unanswered"]:
        print("\nUNANSWERED groups:", ", ".join(result["unanswered"]))
        print("Answer them yourself in the browser, then continue.")

    all_ok = bool(result["summary"]) and not result["unanswered"] and all(
        "strongly agree" in s["a"] or s["a"].startswith(("yes", "true", "y"))
        for s in result["summary"]
    )
    if AUTO_SUBMIT and all_ok:
        log.info("All %d answers are Yes/Strongly Agree. Auto-submitting.", len(result["summary"]))
        add_comment(driver, DEFAULT_COMMENT)
        return submit_and_wait(driver)

    log.warning("Not every answer is Yes/Strongly Agree, so asking you first.")
    comment = ask(f"\nComment [Enter = '{DEFAULT_COMMENT}', '-' = none]: ")
    if comment == "-":
        comment = ""
    elif not comment:
        comment = DEFAULT_COMMENT
    add_comment(driver, comment)

    choice = ask("Type 'y' to SUBMIT, anything else to skip this form: ").lower()
    if choice != "y":
        log.info("Skipped (not submitted).")
        return False
    return submit_and_wait(driver)


TIMELINE_ITEMS_XPATH = "//ul[contains(@class,'timeline')]/li"
FEEDBACK_IN_ITEM_XPATH = (
    ".//a[contains(@class,'btn') and contains(.,'Feedback') "
    "and not(contains(.,'Post Message'))]"
)


def get_items(driver):
    return driver.find_elements(By.XPATH, TIMELINE_ITEMS_XPATH)


def item_feedback_button(item):
    for el in item.find_elements(By.XPATH, FEEDBACK_IN_ITEM_XPATH):
        try:
            if el.is_displayed():
                return el
        except StaleElementReferenceException:
            continue
    return None


def open_item(driver, item):
    try:
        panel = item.find_element(By.XPATH, ".//div[contains(@class,'text')]")
        if panel.is_displayed():
            return
        header = item.find_element(By.XPATH, ".//div[@class='subject']")
        click_element(driver, header)
        WebDriverWait(driver, 3).until(lambda d: panel.is_displayed())
    except Exception as e:
        log.debug("open_item: %s", e)


def scan_all_subjects(driver):
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.XPATH, TIMELINE_ITEMS_XPATH))
        )
    except TimeoutException:
        log.warning("No faculty list found. Falling back to manual mode.")
        return
    total = len(get_items(driver))
    log.info("Found %d faculty entries. Scanning...", total)

    done = 0
    for i in range(total):
        items = get_items(driver)
        if i >= len(items):
            log.info("Page changed; reopening My Faculty.")
            open_my_faculty(driver)
            time.sleep(2)
            items = get_items(driver)
            if i >= len(items):
                break
        item = items[i]
        try:
            subject = item.find_element(By.XPATH, ".//div[@class='subject']").text.strip()
            faculty = item.find_element(
                By.XPATH, ".//*[contains(@class,'faculty-name')]"
            ).get_attribute("textContent").strip()
        except Exception:
            subject, faculty = "?", "?"
        log.info("[%d/%d] %s | %s", i + 1, total, subject, faculty)

        open_item(driver, item)
        time.sleep(0.4)
        btn = item_feedback_button(item)
        if btn is None:
            log.info("  No Feedback button (already submitted).")
            continue

        if process_feedback(driver, btn):
            done += 1
            log.info("  Submitted.")
            time.sleep(1.5)
        else:
            log.error("  Submission failed.")
    log.info("Auto scan finished. Submitted %d of %d.", done, total)

def watch_and_fill(driver):
    log.info("Watching for Feedback button. Click a faculty row to begin. Ctrl+C to stop.")
    last_el = None

    while True:
        try:
            btn = get_feedback_button(driver)

            if btn is None:
                last_el = None
                time.sleep(0.3)
                continue

            if last_el is not None and btn.id == last_el:
                time.sleep(0.3)
                continue

            log.info("Feedback button detected. Filling...")
            if process_feedback(driver, btn):
                log.info("Submitted. Click next faculty row when ready.")
            else:
                log.error("Not submitted for this faculty")
            last_el = btn.id

            time.sleep(0.3)

        except KeyboardInterrupt:
            log.info("Stopped.")
            break
        except StaleElementReferenceException:
            # Keep last_el: only a missing button (None above) re-arms the watcher,
            # so a stale reference can never trigger a second submit.
            time.sleep(0.3)
        except Exception:
            log.exception("Unexpected error in watch loop")
            time.sleep(1)


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Fill Amizone faculty feedback forms. You log in and solve the CAPTCHA yourself."
    )
    p.add_argument("--comment", default=None,
                   help="Comment to put in every feedback box. Omit to be asked; use --comment '' for none.")
    p.add_argument("--ask-before-submit", action="store_true",
                   help="Never auto-submit: show the answers and ask for confirmation on every form.")
    p.add_argument("--chrome-version", type=int, default=None, metavar="N",
                   help="Chrome major version to match (for example 138). Auto-detected by default; "
                        "set it if you get a ChromeDriver version mismatch error.")
    p.add_argument("--login-timeout", type=int, default=LOGIN_TIMEOUT, metavar="SECONDS",
                   help=f"How long to wait for you to log in (default {LOGIN_TIMEOUT}).")
    p.add_argument("--delay", type=float, default=SELECTION_DELAY, metavar="SECONDS",
                   help=f"Pause between selecting answers (default {SELECTION_DELAY}).")
    p.add_argument("--debug", action="store_true", help="Verbose logging.")
    return p.parse_args(argv)


def main():
    global DEFAULT_COMMENT, AUTO_SUBMIT, LOGIN_TIMEOUT, SELECTION_DELAY
    args = parse_args()
    if args.debug:
        log.setLevel(logging.DEBUG)
    AUTO_SUBMIT = not args.ask_before_submit
    LOGIN_TIMEOUT = args.login_timeout
    SELECTION_DELAY = args.delay
    if args.comment is None:
        DEFAULT_COMMENT = ask("Default comment for the feedback box (your own words; blank = none): ")
    else:
        DEFAULT_COMMENT = args.comment

    try:
        driver = make_driver(args.chrome_version)
    except Exception as e:
        log.error("Could not start Chrome: %s", e)
        log.error("Check that Google Chrome is installed and up to date. If the message mentions a "
                  "ChromeDriver version, re-run with --chrome-version <your Chrome's major number> "
                  "(open chrome://version to see it).")
        sys.exit(1)

    try:
        wait_for_login(driver)
        open_my_faculty(driver)
        scan_all_subjects(driver)
        watch_and_fill(driver)
    except RuntimeError as e:
        log.error("%s", e)
    except KeyboardInterrupt:
        log.info("Stopped.")
    finally:
        try:
            input("\nPress Enter to close browser...")
        except (EOFError, KeyboardInterrupt):
            pass
        driver.quit()


if __name__ == "__main__":
    main()