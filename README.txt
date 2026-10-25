TRAIN RESERVATION ACCESSIBILITY CHECKER

Contents
- train_accessibility_checker.py: single Python checker; all logic is included.
- train_reservation_broken.html: unchanged copy of your supplied form.
- train_accessibility_report.txt: actual readable report from the attached form.
- train_accessibility_report.json: structured findings for further processing.

Setup (if Playwright is not already installed)
  python -m pip install playwright
  python -m playwright install chromium

Run
  python train_accessibility_checker.py
Optional visible browser:
  python train_accessibility_checker.py --headed --slow-mo 100
Alternative local HTML path:
  python train_accessibility_checker.py --html "C:/path/train_reservation_broken.html"

Jupyter: extract the ZIP into your notebook folder and run ONE cell:

import subprocess
import sys
from pathlib import Path
script = Path('train_checker/train_accessibility_checker.py').resolve()
result = subprocess.run([sys.executable, str(script)],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding='utf-8', errors='replace')
print(result.stdout)
if result.returncode != 0:
    print('Execution failed. See the error above.')

If the notebook is inside train_checker, change the script path to
Path('train_accessibility_checker.py').resolve().

Verified original-form result
27 observed issues, 3 manual-review items, 24 passed checks.
Includes labels, association, computed names, required indicators, submission
validation, errors, radio keyboard/click behavior, terms trigger, status messages
and the light-gray passenger hint's 1.90:1 contrast.

All findings include criterion/guidance, Actual, Expected, numbered
Recommendations and evidence when useful. The report distinguishes behavioral
and UX guidance from specific WCAG findings. Related findings may share one fix;
these counts are not counts of independent WCAG failures.

Important observation
The Mobile Number label is VISIBLE in the supplied file: .field>label is more
specific than .hidden-label. The checker does not treat the class name itself
as proof of hidden content.

Limits
This is tailored to the attached RailGo sample and uses known field IDs and
intended label relationships. Required status comes from visible asterisks,
native/ARIA attributes or the inspected existing validation rules. It is not a
universal URL auditor. It does not alter the form, perform real bookings, record
screen-reader speech or certify complete WCAG compliance. Terms-panel modality
and the help-symbol name require manual review. No other Python file is imported.

Verification
Ran the full checker in Chromium successfully. Also verified that correcting
Travel Class naming removes its findings, hiding the phone label with actual
rendered CSS creates a visible-label finding, and adding working radio handlers
clears the tested radio interaction findings.
