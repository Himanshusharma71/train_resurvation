#!/usr/bin/env python3
"""RailGo training-form checker. Python 3.9+ and Playwright only.

SETUP:
  python -m pip install playwright
  python -m playwright install chromium
RUN (keep the supplied HTML beside this script):
  python train_accessibility_checker.py
  python train_accessibility_checker.py --html "C:/path/train_reservation_broken.html"
  python train_accessibility_checker.py --headed --slow-mo 100

Writes train_accessibility_report.txt and train_accessibility_report.json.
No external Python module, BeautifulSoup, or test fixture is imported.

This is a targeted auditor for the attached RailGo fixture, not a universal
WCAG conformance checker. It never changes the HTML. Local form submissions
are intercepted by the existing demo JS; no real reservation is made.
ISSUE = observed defect in the stated check. REVIEW = human judgement needed.
Keyboard/APG and requested UX recommendations are not blanket WCAG failures.
Browser AX names are evidence, not a recording of NVDA/JAWS speech.
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

# Intended field/label relationships for this inspected training fixture.
# These titles are known test expectations, not names invented from CSS classes.
FIELDS = {
    'from': 'From station', 'to': 'To station', 'departure': 'Departure Date',
    'train': 'Train', 'travel-class': 'Travel Class', 'passengers': 'Number of Passengers',
    'full-name': 'Full Name', 'age': 'Age', 'phone': 'Mobile Number', 'email': 'Email Address',
}
# Evidence: asterisks/native attributes, or the demo's existing submission rules.
REQUIRED = {
    'from': 'the demo submission handler rejects an empty origin',
    'to': 'visible asterisk and native required attribute',
    'departure': 'visible asterisk and native required attribute',
    'passengers': 'visible asterisk',
    'full-name': 'visible asterisk, aria-required and submission validation',
    'email': 'visible asterisk',
}
SOURCES = {
    'labels': 'https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions',
    'relationships': 'https://www.w3.org/WAI/WCAG22/Understanding/info-and-relationships',
    'name': 'https://www.w3.org/WAI/WCAG22/Understanding/label-in-name',
    'errors': 'https://www.w3.org/WAI/WCAG22/Understanding/error-identification',
    'radio': 'https://www.w3.org/WAI/ARIA/apg/patterns/radio/',
    'status': 'https://www.w3.org/WAI/WCAG22/Understanding/status-messages',
    'contrast': 'https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum',
}
VISIBLE = """el => {
    if (!el || !el.textContent.trim()) return false;
    for(let n=el; n && n.nodeType===1; n=n.parentElement) {
        const s=getComputedStyle(n);
        if(n.hidden || s.display==='none' || s.visibility==='hidden' ||
           s.visibility==='collapse' || Number(s.opacity)===0 || s.clipPath==='inset(50%)') return false;
    }
    const r=el.getBoundingClientRect(); return r.width>0 && r.height>0;
}"""
LIVE = """el => {
    for(let n=el;n;n=n.parentElement) {
        const live=n.getAttribute('aria-live');
        if(live==='off') return false;
        if(live==='polite'||live==='assertive') return true;
        if(['status','alert','log'].includes(n.getAttribute('role'))) return true;
    }
    return false;
}"""


def normalize(text):
    return ' '.join(re.findall(r'\w+', re.sub(r'\(required\)', '', text, flags=re.I).casefold()))


def visible(locator):
    return locator.count() == 1 and locator.evaluate(VISIBLE)


def ax(cdp, selector):
    root = cdp.send('DOM.getDocument')['root']['nodeId']
    node_id = cdp.send('DOM.querySelector', {'nodeId': root, 'selector': selector})['nodeId']
    if not node_id:
        raise RuntimeError('Expected fixture element missing: '+selector)
    backend = cdp.send('DOM.describeNode', {'nodeId': node_id})['node']['backendNodeId']
    nodes = cdp.send('Accessibility.getPartialAXTree', {'backendNodeId': backend, 'fetchRelatives': False})['nodes']
    node = next(n for n in nodes if n.get('backendDOMNodeId') == backend)
    return {
        'role': node.get('role', {}).get('value', ''),
        'name': node.get('name', {}).get('value', ''),
        'description': node.get('description', {}).get('value', ''),
        'states': {p['name']: p['value'].get('value') for p in node.get('properties', [])},
    }


class Report:
    def __init__(self, path):
        self.path, self.findings, self.passes, self.observations = str(path), [], [], []

    def add(self, category, selector, criterion, actual, expected, recommendations, status='ISSUE', evidence=None):
        self.findings.append(dict(id=f'ISSUE-{len(self.findings)+1:03}', status=status,
                                  category=category, selector=selector, criterion=criterion,
                                  actual=actual, expected=expected,
                                  recommendations=recommendations, evidence=evidence or {}))

    def text(self):
        counts = Counter(f['status'] for f in self.findings)
        lines = ['TRAIN RESERVATION ACCESSIBILITY REPORT', 'Source: '+self.path,
                 f"Observed issues: {counts['ISSUE']} | Manual review: {counts['REVIEW']} | Passed checks: {len(self.passes)}",
                 'Scope: labels, associations, names, required indicators, validation, custom radios,',
                 'terms trigger, status updates and selected text contrast. Not a full WCAG audit.', '']
        for f in self.findings:
            lines += [f"{f['id']} [{f['status']}] {f['category']} | {f['selector']}",
                      'Criterion / guidance: '+f['criterion'], 'Actual: '+f['actual'],
                      'Expected: '+f['expected'], 'Recommendation:']
            lines += [f'{i}. {r}' for i, r in enumerate(f['recommendations'], 1)]
            if f['evidence']:
                lines += ['Evidence: '+json.dumps(f['evidence'], ensure_ascii=False)]
            lines += ['']
        lines += ['PASSED CHECKS'] + ['- '+x for x in self.passes]
        lines += ['', 'OBSERVATIONS / LIMITS'] + ['- '+x for x in self.observations]
        lines += ['', 'REFERENCE GUIDANCE'] + list(SOURCES.values())
        return '\n'.join(lines)


def check_labels(page, cdp, report):
    for fid, title in FIELDS.items():
        control = page.locator('#'+fid)
        if control.count() != 1:
            raise RuntimeError('Input does not match this RailGo fixture: #'+fid)
        label = page.locator(f'.field:has(> #{fid}) > label, .field:has(> #{fid}) > .field-label').first
        name = ax(cdp, '#'+fid)['name']
        has_visible_label = visible(label)
        recs = [f'Provide a visible <label> for this field, e.g. "{title}".',
                f'Use the unique control id "{fid}" and set the label for attribute to "{fid}".',
                'Keep the label visible before and after entering a value.']
        if not has_visible_label:
            report.add('Visible label', '#'+fid, '3.3.2 — Labels or Instructions',
                       f'The field has no visible purpose label. Computed accessible name: {name!r}.',
                       'A persistent visible label identifies the field.', recs)
        else:
            report.passes.append('#'+fid+': visible label present')
            associated = control.evaluate(r"""el => {
                const label=el.closest('.field').querySelector(':scope > label, :scope > .field-label');
                return [...(el.labels||[])].includes(label) ||
                    (label.id && (el.getAttribute('aria-labelledby')||'').split(/\s+/).includes(label.id));
            }""")
            if not associated:
                report.add('Label association', '#'+fid, '1.3.1 — Info and Relationships',
                           f'The visible label {label.inner_text().strip()!r} is not programmatically associated with this control.',
                           'The intended label and field have a programmatic relationship.',
                           [f'Use <label for="{fid}"> for the visible label.',
                            f'Ensure the control id="{fid}" is unique and matches for exactly.',
                            'Alternatively, give the existing visible span a unique id and reference it with aria-labelledby.'])
            else:
                report.passes.append('#'+fid+': label association present')
            label_text = label.inner_text().replace('*', '').strip()
            if name and f' {normalize(label_text)} ' not in f' {normalize(name)} ':
                report.add('Visible label / accessible name mismatch', '#'+fid, '2.5.3 — Label in Name',
                           f'Visible label is {label_text!r}; Chromium-computed accessible name is {name!r}.',
                           'The accessible name contains the visible label text in the same order.',
                           [f'Remove the conflicting aria-label and associate the visible label "{title}".',
                            'If ARIA naming is needed, include the visible label in the effective accessible name.',
                            'Check aria-labelledby first, because it takes precedence over aria-label.'])
            elif name:
                report.passes.append('#'+fid+': visible label included in accessible name')
        if not name.strip():
            report.add('Missing accessible name', '#'+fid, '4.1.2 — Name, Role, Value',
                       'Chromium exposes an empty accessible name for this field.',
                       'The field has a meaningful programmatic name.', recs,
                       evidence=ax(cdp, '#'+fid))
        if fid == 'phone' and has_visible_label:
            display = label.evaluate('el=>getComputedStyle(el).display')
            report.observations.append(f'#phone: .hidden-label is present but computed display is {display!r}; '
                                       '.field>label overrides display:none. No hidden-label failure reported.')
        if fid in REQUIRED:
            required = control.evaluate("el=>el.required===true || el.getAttribute('aria-required')==='true'")
            if not required:
                report.add('Required state', '#'+fid, '1.3.1 — Info and Relationships / required-state technique',
                           f'Required by {REQUIRED[fid]}, but neither required nor aria-required="true" is supplied.',
                           'The required state is programmatically exposed.',
                           [f'Add required to the native control #{fid}, or aria-required="true" where appropriate.',
                            'Ensure validation enforces the business rule; aria-required alone does not validate.'])
            else:
                report.passes.append('#'+fid+': required attribute/state supplied')
            if not has_visible_label or not re.search(r'\*|required', label.inner_text(), re.I):
                report.add('Visible required indicator', '#'+fid, '3.3.2 — Labels or Instructions',
                           'The required field is not visibly identified as required.',
                           'Required status is clear before submission.',
                           ['Add "(required)" or an asterisk next to its visible label.',
                            'If using an asterisk, explain its meaning before the form.'])
    if page.locator('label, .field-label').filter(has_text='*').count():
        explained = bool(re.search(r'(asterisk|marked with).{0,90}required', page.locator('body').inner_text(), re.I))
        if not explained:
            report.add('Required asterisk explanation', '#reservation', '3.3.2 — Labels or Instructions',
                       'Several labels contain *, but the form does not explain its meaning.',
                       'The meaning of required-field markers is stated before the form.',
                       ['Add before the form: "Fields marked with an asterisk (*) are required."',
                        'Alternatively, use the text "(required)" beside each required label.'])
    # Native radio labels are already implicit; audit the group, not each div.
    gender = page.locator('[data-test="TC09"]')
    grouped = gender.evaluate("el=>Boolean(el.closest('fieldset')?.querySelector('legend')) || Boolean(el.closest('[role=radiogroup]')?.getAttribute('aria-labelledby'))")
    if not grouped:
        report.add('Native radio group label', '[data-test="TC09"]', '1.3.1 — Info and Relationships',
                   'Female, Male and Other have individual labels, but the visible Gender heading is not a group label.',
                   'The relationship between Gender and its options is programmatically available.',
                   ['Wrap the native radios in <fieldset> with <legend>Gender</legend>.',
                    'Retain their shared name="gender" and existing individual labels.'])
    group_ax = ax(cdp, '#berth-group')
    if not group_ax['name']:
        report.add('Custom radio group name', '#berth-group', '1.3.1 / 4.1.2 — Group relationship and name',
                   'The radiogroup has an empty computed name; Berth Preference is only adjacent visible text.',
                   'The radio group is named by its visible heading.',
                   ['Give the Berth Preference span a unique id, e.g. berth-label.',
                    'Set aria-labelledby="berth-label" on #berth-group.',
                    'Retain role="radio" and valid aria-checked states on the options.'], evidence=group_ax)
    help_name = ax(cdp, '#help')['name']
    if normalize(help_name) in ('', 'i'):
        report.add('Help button name quality', '#help', 'Review 4.1.2 — meaningful accessible name',
                   f'The computed name is {help_name!r}, a symbol rather than an explicit purpose label.',
                   'Users can understand that this button opens help.',
                   ['Add aria-label="Help with train reservation" or meaningful visible button text.',
                    'Verify the result with a screen reader.'], status='REVIEW')


def check_errors(page, report, reset):
    error_recs = ['Identify each invalid field and describe the problem with specific error text.',
                  'Give each error a unique id and include that id in the field aria-describedby (preserve existing hint IDs).',
                  'Set aria-invalid="true" after failure and clear it when the field is corrected.',
                  'After a failed submission, focus the first invalid field or an accessible linked error summary.']
    reset()
    page.locator('button[type=submit]').click()
    expect(page.locator('#form-error')).not_to_have_text('')
    summary = page.locator('#form-error').inner_text()
    for fid in REQUIRED:
        error = page.locator(f'.field:has(> #{fid}) .error:visible')
        refs = page.locator('#'+fid).get_attribute('aria-describedby') or ''
        if error.count() == 0:
            report.add('Missing field-specific error', '#'+fid, '3.3.1 — Error Identification; validation coverage',
                       f'Empty submission shows only {summary!r}; this field has no visible identifying error. '
                       f'Required evidence: {REQUIRED[fid]}.',
                       'Missing required input is identified and the error described in text.', error_recs,
                       evidence={'aria_describedby': refs})
        else:
            eid = error.first.get_attribute('id')
            if not eid or eid not in refs.split():
                report.add('Error association', '#'+fid, '1.3.1 — Info and Relationships',
                           'Visible field error is not associated through aria-describedby in this fixture.',
                           'The error is programmatically associated with its field.', error_recs)
    focus = page.evaluate('document.activeElement.outerHTML')
    if page.locator('button[type=submit]').evaluate('el=>document.activeElement===el'):
        report.add('Focus after failed submission', '#reservation', 'Requested UX check — not a standalone WCAG failure',
                   'Focus remains on Reserve Seat after the failed submission.',
                   'Users can promptly locate and correct the first error.', error_recs, status='REVIEW', evidence={'focus':focus})
    if not page.locator('#form-error').evaluate(LIVE):
        report.add('Validation status announcement', '#form-error', '4.1.3 — Status Messages',
                   'Submission changes error/status text without live-region semantics or focus on the message.',
                   'The status update is programmatically available without requiring the user to locate it.',
                   ['Use a pre-existing role="alert" or appropriate live region for the validation summary.',
                    'Provide specific errors and avoid duplicate announcements when moving focus.'])
    reset()
    for fid, value in {'from':'Delhi','to':'Jhansi','full-name':'Demo Passenger','email':'bad-email','passengers':'0'}.items():
        page.locator('#'+fid).fill(value)
    page.locator('button[type=submit]').click()
    expect(page.locator('#form-error')).not_to_have_text('')
    summary = page.locator('#form-error').inner_text()
    invalid = page.locator('#email, #passengers, #departure').evaluate_all(
        'els=>els.map(el=>({id:el.id, valid:el.validity.valid, message:el.validationMessage}))')
    if 'submitted' in summary.lower() and any(not i['valid'] for i in invalid):
        report.add('Invalid values accepted', '#reservation', 'Validation defect; related to 3.3.1 / 3.3.3',
                   'The form reports a submitted request despite an invalid email, zero passengers, and missing required departure date.',
                   'The form validates required values and formats before reporting success.',
                   ['Validate all required fields, the email format, and the passenger range (1–6).',
                    'Because novalidate is used, implement the complete custom validation flow or restore accessible native validation.',
                    'Show field-specific errors, associate them, and report success only after all rules pass.'],
                   evidence={'result':summary,'native_validity':invalid})


def check_radio_behavior(page, report, reset):
    failures = []
    def state():
        return page.locator('#berth-group').evaluate("""g=>({
            focus:document.activeElement.getAttribute('data-value'),
            checked:[...g.querySelectorAll('[aria-checked=true]')].map(e=>e.dataset.value),
            tabStops:[...g.querySelectorAll('[role=radio]')].filter(e=>e.tabIndex===0).map(e=>e.dataset.value)
        })""")
    for key, target in [('ArrowRight','upper'),('ArrowDown','upper'),('ArrowLeft','side'),('ArrowUp','side'),('Space','upper')]:
        reset()
        source = 'upper' if key=='Space' else 'lower'
        page.locator(f'[data-value="{source}"]').focus()
        page.keyboard.press(key)
        actual = state()
        expected = dict(focus=target, checked=[target], tabStops=[target])
        if actual != expected:
            failures.append({'key':key,'actual':actual,'expected':expected})
    if failures:
        report.add('Custom radio keyboard interaction', '#berth-group', 'APG radio pattern; review keyboard operability under 2.1.1',
                   'Arrow keys and Space do not update the tested focus/selection/tabindex states.',
                   'Standard radio keys operate the group and keep checked state and focus synchronized.',
                   ['Prefer native <input type="radio"> controls with labels and a shared name.',
                    'For custom radios, implement ArrowRight/Down for next and ArrowLeft/Up for previous, wrapping at both ends.',
                    'Space checks the focused option. Set only one aria-checked="true".',
                    'Keep tabindex="0" on the checked option (first option if none checked), and "-1" on the others.'],
                   evidence={'failed_actions':failures})
    reset()
    page.locator('[data-value="upper"]').click()
    actual = state()
    if actual['checked'] != ['upper']:
        report.add('Custom radio pointer selection', '#berth-group', 'Functional defect / state synchronization',
                   'Clicking Upper leaves Lower checked.',
                   'Clicking a radio updates the selection and its programmatic state.',
                   ['Handle click selection using the same update function as the keyboard handlers.',
                    'Update aria-checked, tabindex, focus and selected appearance together.'], evidence=actual)


def check_terms_and_status(page, report, reset):
    reset()
    page.locator('#search-trains').click()
    expect(page.locator('#train-results')).to_be_visible()
    if not page.locator('#train-results').evaluate(LIVE):
        report.add('Search results announcement', '#train-results', '4.1.3 — Status Messages',
                   'Find Trains reveals the results count without status/live-region semantics; focus stays on the button.',
                   'The result count is available to assistive technology as a status update.',
                   ['Create an initially empty, visible role="status" container before the action.',
                    'Update its text to "3 trains found" after search; keep the result list separately structured.'])
    reset()
    target = page.locator('.fake-link')
    reachable = target.evaluate('el=>el.tabIndex>=0')
    target.evaluate('el=>el.focus()')
    focused = target.evaluate('el=>el===document.activeElement')
    page.keyboard.press('Enter')
    opened_by_key = page.locator('#terms-dialog').is_visible()
    target.click()
    expect(page.locator('#terms-dialog')).to_be_visible()
    if not reachable and not focused and not opened_by_key:
        report.add('Terms trigger keyboard access', '.fake-link', '2.1.1 — Keyboard / 4.1.2 — Name, Role, Value',
                   'The clickable span opens Terms with a mouse, but has no native button role, is outside the Tab sequence and cannot receive focus for Enter activation.',
                   'The action is reachable and operable by keyboard with appropriate semantics.',
                   ['Replace the span with <button type="button">Terms and conditions</button>.',
                    'Place the separate terms button outside the checkbox label to avoid nested interactive controls.',
                    'Keep a clear visible focus indicator and a meaningful accessible name.'])
    # This panel may be intended as an inline disclosure, so do not assume modality.
    panel_role = page.locator('#terms-dialog').get_attribute('role')
    if panel_role != 'dialog':
        report.add('Terms panel design', '#terms-dialog', 'Manual design review — disclosure versus dialog',
                   'The revealed terms content is an ordinary div. Its name suggests a dialog, but the page does not establish modal behavior.',
                   'Choose and implement a consistent disclosure or dialog pattern.',
                   ['For an inline disclosure, use a button with aria-expanded and aria-controls; keep content in logical reading order.',
                    'If a modal dialog is intended, use a named <dialog> opened with showModal(), initial focus, Escape close and focus return.',
                    'Do not add aria-modal="true" unless interaction outside the dialog is actually blocked.'], status='REVIEW')


def check_contrast(page, report, reset):
    reset()
    target = page.locator('.low-contrast')
    style = target.evaluate("""el=>{
        const s=getComputedStyle(el);let background='rgb(255, 255, 255)';
        for(let n=el;n;n=n.parentElement){const bg=getComputedStyle(n).backgroundColor;
            if(bg!=='rgba(0, 0, 0, 0)' && bg!=='transparent'){background=bg;break;}}
        return {color:s.color,background,size:s.fontSize,weight:s.fontWeight,text:el.innerText};
    }""")
    def luminance(rgb):
        values = [float(x)/255 for x in re.findall(r'[\d.]+', rgb)[:3]]
        linear = [v/12.92 if v<=0.04045 else ((v+0.055)/1.055)**2.4 for v in values]
        return sum(a*b for a,b in zip(linear,[0.2126,0.7152,0.0722]))
    a,b = sorted([luminance(style['color']),luminance(style['background'])])
    ratio = (b+0.05)/(a+0.05)
    # Target is ordinary 16px normal-weight text on an opaque white panel.
    if ratio < 4.5:
        report.add('Text contrast', '.low-contrast', '1.4.3 — Contrast (Minimum)',
                   f'The text {style["text"]!r} has contrast {ratio:.2f}:1 ({style["color"]} on {style["background"]}).',
                   'Normal-size text has at least 4.5:1 contrast.',
                   ['Use a darker foreground, e.g. #475569 on white.',
                    'Recheck the rendered foreground/background contrast after the change.'], evidence=style)
    else:
        report.passes.append('.low-contrast: contrast meets 4.5:1 for the tested colors')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--html', default=str(Path(__file__).with_name('train_reservation_broken.html')))
    parser.add_argument('--out', default=str(Path(__file__).parent))
    parser.add_argument('--headed', action='store_true')
    parser.add_argument('--slow-mo', type=int, default=0)
    args = parser.parse_args()
    source = Path(args.html).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f'HTML not found: {source}. Keep it beside this script or use --html.')
    report = Report(source)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, slow_mo=args.slow_mo)
        page = browser.new_page()
        page.on('dialog', lambda dialog: dialog.dismiss())
        cdp = page.context.new_cdp_session(page)
        def reset():
            page.goto(source.as_uri(), wait_until='load')
        try:
            reset()
            check_labels(page, cdp, report)
            check_errors(page, report, reset)
            check_radio_behavior(page, report, reset)
            check_terms_and_status(page, report, reset)
            check_contrast(page, report, reset)
        finally:
            cdp.detach()
            browser.close()
    report.observations += [
        'Existing label text, browser AX names, rendered CSS and actual interactions were inspected; data-test IDs were not treated as proof of a failure.',
        'Error associations are not reported as separate confirmed defects when no corresponding visible error exists; recommendations explain how to provide and associate it.',
        'A symbol-only help name and the terms-panel design require human review.',
        'The visibility probe is limited; occlusion, complex clipping, screen-reader speech, semantic wording and full WCAG coverage still require additional tests.',
        'Required assumptions come from the inspected fixture rules/asterisks. Confirm actual business rules before applying this checker to a different page.',
    ]
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    txt = out/'train_accessibility_report.txt'
    js = out/'train_accessibility_report.json'
    txt.write_text(report.text(), encoding='utf-8')
    js.write_text(json.dumps(dict(source=report.path, findings=report.findings,
                                  passed_checks=report.passes, observations=report.observations,
                                  references=SOURCES), ensure_ascii=False, indent=2), encoding='utf-8')
    print(report.text())
    print('\nSaved:', txt, '\nSaved:', js)
    print('CHECK COMPLETED. Findings are reported above; the source form was not changed.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'EXECUTION ERROR: {exc}', file=sys.stderr)
        sys.exit(1)
