# Amizone Feedback Helper

Fills in the faculty feedback forms on the Amizone student portal so you don't have to click through every radio button yourself.

**How it works:** it opens Chrome, **you log in and solve the CAPTCHA**, then it goes through *My Faculty*, selects **Yes / Strongly Agree** on each form, prints every question with the answer it picked, and submits. If any answer is not a clear Yes / Strongly Agree, it stops and asks you instead of submitting.

> **Read this first.** The script never logs in for you and never stores your password. It only clicks what is on your screen. You are responsible for what is submitted on your account, so read the answers it prints. Check that automating the portal is allowed by your university before using it. Not affiliated with Amizone or Amity.

## Quick start

You need **Google Chrome** and **Python 3.9 or newer** ([python.org/downloads](https://www.python.org/downloads/); on Windows tick *Add python.exe to PATH* in the installer).

### Windows

1. Download this repository (green **Code** button → **Download ZIP**) and unzip it.
2. Double-click **`run.bat`**.
3. Wait for Chrome to open. Log in on the Amizone page and solve the CAPTCHA.
4. Watch the terminal. When it says it is done, press Enter to close the browser.

### macOS / Linux

```bash
git clone https://github.com/SahilYadav-op/amizone-feedback-helper.git
cd amizone-feedback-helper
./run.sh
```

The first run creates a `.venv` folder and installs what it needs (about a minute). Later runs start straight away.

## Options

Pass them after the launcher, e.g. `run.bat --comment "Clear lectures"`.

| Option | What it does |
| :--- | :--- |
| `--comment "text"` | Put this text in every comment box. Without it you are asked once at the start. Use `--comment ""` for no comment. |
| `--ask-before-submit` | Never auto-submit. Show the answers and ask `y` on every form. |
| `--chrome-version 138` | Match this Chrome major version (see the fix for *"This version of ChromeDriver only supports…"* below). |
| `--login-timeout 300` | Seconds to wait for you to log in (default 180). |
| `--delay 0.2` | Seconds between selecting answers (default 0.5). |
| `--debug` | Verbose logs, useful when reporting a problem. |

## Troubleshooting

| Problem | Fix |
| :--- | :--- |
| `Python 3.9 or newer was not found` | Install Python and make sure *Add python.exe to PATH* was ticked, then run again. |
| `This version of ChromeDriver only supports Chrome version X` | The script normally detects your Chrome version. If it can't, open `chrome://version`, note the first number (for example `138`), and run with `--chrome-version 138`. Updating Chrome also fixes it. |
| `ModuleNotFoundError: distutils` | You are on Python 3.12+ without setuptools. `run.bat` / `run.sh` install it for you; if running by hand use `pip install -r requirements.txt`. |
| Chrome opens, then closes straight away | Close every other Chrome window and try again. If you use a managed or work Chrome profile, try a clean Windows user. |
| `Login not detected within the timeout` | You took longer than 180 s. Run again with `--login-timeout 600`. |
| It says *Could not find 'My Faculty'* | Click **My Faculty** in the portal menu yourself. The script then continues. |
| Some forms say *Unanswered question groups* | Those questions have no Yes / Strongly Agree option. Answer them in the browser, then follow the prompt. |
| `Submission failed` | The portal showed an error popup. Read the message in the terminal, fix the form by hand, and run again. Forms already submitted are skipped. |
| The portal layout changed and nothing is found | The page selectors are at the top of `main.py` (`SUBMIT_XPATHS`, `MY_FACULTY_XPATHS`, `TIMELINE_ITEMS_XPATH`). Open an issue with `--debug` output. |

### Running by hand (any OS)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate        macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## License

MIT. See [LICENSE](./LICENSE). © Sahil Yadav.
