"""Synthetic enterprise corpus + ground-truth QA generator.

Builds a fictional company ("Halvorsen Industrial Systems") document estate in
four formats (PDF, DOCX, CSV, Markdown).  Every fact written into a document is
recorded at the same time together with the document name and page (PDF/DOCX
page, CSV data-row number, Markdown section number), so the ground-truth
labels are exact by construction.  ``validate_ground_truth`` re-parses the files
to prove that each answer really sits on its labelled page.

No real company, person or customer data is used.
"""
from __future__ import annotations

import csv
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import config

COMPANY = "Halvorsen Industrial Systems"


@dataclass
class Fact:
    fact_id: str
    doc: str
    page: int
    questions: list[str]
    answer: str            # short canonical value exactly as it appears in the source
    gold_answer: str       # full reference answer sentence
    doc_type: str
    topic: str = ""
    extra: dict = field(default_factory=dict)


class FactBook:
    def __init__(self):
        self.facts: list[Fact] = []

    def add(self, doc, page, questions, answer, gold, doc_type, topic=""):
        fid = f"F{len(self.facts) + 1:04d}"
        self.facts.append(Fact(fid, doc, page, list(questions), str(answer), gold, doc_type, topic))


# ---------------------------------------------------------------------------
# Prose sections: (title, intro, [(sentence, answer, [questions...]), ...])
# ---------------------------------------------------------------------------
HANDBOOK = [
    ("1. About This Handbook",
     f"This handbook describes the employment policies of {COMPANY}. It applies to all permanent and fixed-term staff in every country where the company operates, unless local law requires otherwise.",
     [("This edition of the handbook takes effect on 1 March 2026 and supersedes the 2023 edition.", "1 March 2026",
       ["When does the current employee handbook take effect?", "What is the effective date of the 2026 handbook edition?"]),
      ("The handbook is owned by the People Operations department.", "People Operations",
       ["Which department owns the employee handbook?", "Who is responsible for maintaining the staff handbook?"]),
      ("The handbook is formally reviewed every 18 months.", "18 months",
       ["How often is the employee handbook reviewed?", "What is the review cycle for the handbook?"]),
      ("Questions about policy interpretation must be raised with the employee's HR Business Partner within 10 working days of the event in question.", "10 working days",
       ["How long do employees have to raise a policy interpretation question with HR?", "Within what time frame must policy interpretation queries be raised?"]),
      ]),
    ("2. Working Hours and Remote Work",
     "Our standard working week is 37.5 hours. Flexible working is encouraged where operational needs allow, but some collaboration time is protected for every team.",
     [("Core collaboration hours are 10:00 to 15:00 local time, during which employees are expected to be available.", "10:00 to 15:00",
       ["What are the core collaboration hours?", "During which hours must employees be reachable each day?"]),
      ("Office-based roles may work remotely for a maximum of 3 days per week.", "3 days per week",
       ["How many days per week can office staff work from home?", "What is the maximum number of remote working days per week?"]),
      ("New remote-eligible employees receive a one-time home office stipend of EUR 450.", "EUR 450",
       ["How much is the home office stipend?", "What one-time allowance do employees receive for setting up a home office?"]),
      ("Company laptops are refreshed every 36 months.", "36 months",
       ["How often are company laptops replaced?", "What is the laptop refresh cycle?"]),
      ("Overtime must be pre-approved by a line manager and is compensated at 150% of the base hourly rate.", "150%",
       ["At what rate is approved overtime paid?", "What is the overtime compensation rate?"]),
      ]),
    ("3. Leave Entitlements",
     "All leave requests are submitted through the HR portal. Managers should respond to requests within five working days.",
     [("Full-time employees receive 25 days of paid annual leave per calendar year in addition to public holidays.", "25 days",
       ["How many days of annual leave do full-time employees get?", "What is the yearly paid holiday entitlement?"]),
      ("A maximum of 5 unused annual leave days may be carried over into the following year.", "5 days",
       ["How many unused leave days can be carried over?", "What is the annual leave carry-over limit?"]),
      ("The primary caregiver is entitled to 20 weeks of fully paid parental leave.", "20 weeks",
       ["How much paid parental leave does a primary caregiver receive?", "What is the parental leave entitlement for the primary caregiver?"]),
      ("Employees may self-certify sickness absence for up to 3 consecutive days before a medical certificate is required.", "3 consecutive days",
       ["For how many days can an employee self-certify sickness?", "When is a medical certificate required for sick leave?"]),
      ("Bereavement leave of 5 paid days is granted on the death of an immediate family member.", "5 paid days",
       ["How much bereavement leave is granted?", "How many paid days off are given after the death of a close family member?"]),
      ]),
    ("4. Travel and Expenses",
     "Business travel must be booked through the corporate travel portal. Employees should choose the most economical option that meets the business need.",
     [("The meal per diem for domestic business travel is EUR 64 per day.", "EUR 64",
       ["What is the daily meal allowance for domestic travel?", "How much per diem can be claimed for meals on domestic trips?"]),
      ("The meal per diem for international business travel is EUR 95 per day.", "EUR 95",
       ["What is the per diem for international business trips?", "How much is the daily meal allowance when travelling abroad?"]),
      ("Economy class must be booked for all flights shorter than 6 hours.", "6 hours",
       ["Below what flight duration is economy class mandatory?", "For which flights must staff fly economy?"]),
      ("Hotel accommodation is capped at EUR 210 per night outside capital cities.", "EUR 210",
       ["What is the nightly hotel limit outside capital cities?", "How much can be spent per night on hotels in non-capital cities?"]),
      ("Expense claims must be submitted within 30 days of the expense being incurred.", "30 days",
       ["What is the deadline for submitting expense claims?", "Within how many days must expenses be claimed?"]),
      ("Use of a private car for business is reimbursed at EUR 0.42 per kilometre.", "EUR 0.42",
       ["What is the mileage reimbursement rate for private cars?", "How much is paid per kilometre for using a personal car on business?"]),
      ]),
    ("5. Information Security",
     "Every employee is responsible for protecting company and customer information. The Information Security Office publishes detailed standards on the intranet.",
     [("Passwords for company accounts must be at least 14 characters long.", "14 characters",
       ["What is the minimum password length?", "How long must company account passwords be?"]),
      ("Multi-factor authentication is mandatory for all remote access to company systems.", "Multi-factor authentication",
       ["What is required for remote access to company systems?", "Which authentication control is mandatory for remote access?"]),
      ("Suspected security incidents must be reported to the Security Operations Centre within 2 hours of discovery.", "2 hours",
       ["How quickly must a suspected security incident be reported?", "What is the reporting deadline for security incidents?"]),
      ("Workstations must lock automatically after 5 minutes of inactivity.", "5 minutes",
       ["After how long must an idle workstation lock?", "What is the automatic screen lock timeout?"]),
      ("All employees must complete phishing awareness training every quarter.", "every quarter",
       ["How often is phishing awareness training required?", "What is the frequency of phishing training?"]),
      ]),
    ("6. Records and Data Retention",
     "Records must be retained for the periods below and then securely destroyed, unless a legal hold applies.",
     [("Financial and accounting records are retained for 7 years.", "7 years",
       ["How long are financial records kept?", "What is the retention period for accounting records?"]),
      ("Personnel files are retained for 6 years after the end of employment.", "6 years",
       ["How long are personnel files kept after an employee leaves?", "What is the retention period for HR records after termination?"]),
      ("CCTV footage is retained for 30 days unless required for an investigation.", "30 days",
       ["How long is CCTV footage stored?", "What is the CCTV retention period?"]),
      ("Customer support tickets are retained for 3 years after closure.", "3 years",
       ["How long are closed customer support tickets kept?", "What is the retention period for support tickets?"]),
      ("System backups are retained for 90 days.", "90 days",
       ["How long are system backups kept?", "What is the backup retention period?"]),
      ]),
    ("7. Code of Conduct",
     "We expect every employee to act with integrity and to avoid situations where personal interests could conflict with those of the company.",
     [("Employees may not accept gifts or hospitality with a value above EUR 75 from suppliers or customers.", "EUR 75",
       ["What is the maximum value of gifts employees may accept?", "Above what value are supplier gifts prohibited?"]),
      ("Potential conflicts of interest must be disclosed to the Compliance Office within 14 days of becoming aware of them.", "14 days",
       ["How soon must a conflict of interest be disclosed?", "What is the deadline for declaring a conflict of interest?"]),
      ("The confidential whistleblowing hotline is operated by an independent provider and is available 24 hours a day.", "24 hours a day",
       ["When is the whistleblowing hotline available?", "What are the operating hours of the whistleblower hotline?"]),
      ("Breaches of the code of conduct are investigated by the Ethics Committee.", "Ethics Committee",
       ["Who investigates code of conduct breaches?", "Which body handles code of conduct investigations?"]),
      ]),
    ("8. Health and Safety",
     "Safety is our first priority. All staff must follow site-specific safety rules in addition to the general rules below.",
     [("Each site must have at least one trained first aider for every 25 employees present.", "every 25 employees",
       ["What is the required ratio of first aiders to employees?", "How many employees can one first aider cover?"]),
      ("Fire evacuation drills are held twice a year at every site.", "twice a year",
       ["How often are fire drills held?", "What is the frequency of fire evacuation drills?"]),
      ("Workplace injuries must be recorded on form HS-7 within 24 hours.", "form HS-7",
       ["Which form is used to record workplace injuries?", "On what form are workplace accidents reported?"]),
      ("Safety footwear is reimbursed up to EUR 120 per year for production staff.", "EUR 120",
       ["How much safety footwear reimbursement do production staff get?", "What is the annual allowance for safety shoes?"]),
      ]),
]

COMPLIANCE = [
    ("1. Scope and Certification",
     f"This manual defines the quality management system of {COMPANY} for the design, manufacture and servicing of industrial pumps and controllers.",
     [("The quality management system is certified to ISO 9001:2015 under certificate number QMS-48213.", "QMS-48213",
       ["What is the ISO 9001 certificate number?", "Under which certificate number is the QMS certified?"]),
      ("The certification body is Nordic Assurance Services.", "Nordic Assurance Services",
       ["Which certification body certified the quality system?", "Who is the ISO 9001 registrar?"]),
      ("The Quality Director is the management representative for the QMS.", "Quality Director",
       ["Who is the management representative for the quality management system?", "Which role represents management for the QMS?"]),
      ("A management review of the QMS is held every 6 months.", "every 6 months",
       ["How often is the QMS management review held?", "What is the frequency of quality management reviews?"]),
      ("The quality manual itself is reviewed annually by the Document Control team.", "annually",
       ["How frequently is the quality manual reviewed?", "When does the Document Control team review the manual?"]),
      ]),
    ("2. Calibration of Measuring Equipment",
     "All inspection, measuring and test equipment is uniquely identified and recorded in the calibration register.",
     [("Torque wrenches are calibrated every 6 months to a tolerance of plus or minus 2 percent.", "plus or minus 2 percent",
       ["What is the calibration tolerance for torque wrenches?", "To what accuracy are torque wrenches calibrated?"]),
      ("Pressure gauges are calibrated every 12 months.", "every 12 months",
       ["How often are pressure gauges calibrated?", "What is the calibration interval for pressure gauges?"]),
      ("Coordinate measuring machines are verified against reference artefacts every 90 days.", "every 90 days",
       ["How often are coordinate measuring machines verified?", "What is the verification interval for CMMs?"]),
      ("Equipment found out of tolerance is tagged with a red QUARANTINE label and removed from use.", "red QUARANTINE label",
       ["How is out-of-tolerance measuring equipment marked?", "What label is applied to equipment that fails calibration?"]),
      ("Calibration records are retained for 10 years.", "10 years",
       ["How long are calibration records retained?", "What is the retention period for calibration certificates?"]),
      ]),
    ("3. Nonconformance and Corrective Action",
     "Any product, process or supplier nonconformance is recorded in the quality system and assigned an owner.",
     [("Nonconformance reports (NCRs) must be closed within 21 days of being raised.", "21 days",
       ["What is the closure deadline for nonconformance reports?", "Within how many days must an NCR be closed?"]),
      ("Root cause analysis for corrective actions uses the 8D method.", "8D method",
       ["Which root cause analysis method is used for corrective actions?", "What problem-solving method is applied to CAPAs?"]),
      ("The effectiveness of each corrective action is verified 90 days after implementation.", "90 days",
       ["When is the effectiveness of a corrective action verified?", "How long after implementation is CAPA effectiveness checked?"]),
      ("Customer complaints must be acknowledged within 2 working days.", "2 working days",
       ["How quickly must customer complaints be acknowledged?", "What is the acknowledgement time for a customer complaint?"]),
      ("A Material Review Board meets every Tuesday to disposition nonconforming material.", "every Tuesday",
       ["When does the Material Review Board meet?", "On which day is nonconforming material dispositioned?"]),
      ]),
    ("4. Internal and Supplier Audits",
     "Audits are planned on a risk basis and carried out by trained auditors who are independent of the area audited.",
     [("Every process in the QMS is internally audited at least once every 12 months.", "once every 12 months",
       ["How often is each QMS process internally audited?", "What is the minimum internal audit frequency per process?"]),
      ("Critical suppliers are audited on site every 24 months.", "every 24 months",
       ["How often are critical suppliers audited on site?", "What is the on-site audit interval for critical suppliers?"]),
      ("Internal auditors must complete a 3-day lead auditor course before conducting audits.", "3-day lead auditor course",
       ["What training must internal auditors complete?", "Which course is required before someone can conduct internal audits?"]),
      ("Major audit findings must have a corrective action plan submitted within 10 days.", "10 days",
       ["How soon must a corrective action plan be submitted for a major audit finding?", "What is the deadline for responding to major audit findings?"]),
      ("Suppliers with a quality score below 70 are placed on probation.", "below 70",
       ["Which quality score puts a supplier on probation?", "At what supplier quality score does probation apply?"]),
      ]),
    ("5. Product Release and Traceability",
     "Finished products are released only after all inspection and test steps defined in the control plan are complete.",
     [("Every pump undergoes a hydrostatic pressure test at 1.5 times its rated pressure before release.", "1.5 times",
       ["At what pressure is the hydrostatic test performed?", "What multiple of rated pressure is used for the pump pressure test?"]),
      ("Pump serial numbers follow the format HX-YYWW-NNNN.", "HX-YYWW-NNNN",
       ["What is the format of pump serial numbers?", "How are pump serial numbers structured?"]),
      ("Traceability records for safety-critical components are retained for 15 years.", "15 years",
       ["How long are traceability records for safety-critical parts kept?", "What is the retention period for safety-critical traceability data?"]),
      ("Final inspection sampling follows ISO 2859-1 with an AQL of 0.65.", "0.65",
       ["What AQL is used for final inspection sampling?", "Which acceptance quality limit applies to final inspection?"]),
      ("The Quality Engineer signs the certificate of conformity for each shipment.", "Quality Engineer",
       ["Who signs the certificate of conformity?", "Which role approves the certificate of conformity for shipments?"]),
      ]),
]

SITES = [("Tampere Works", "Finland"), ("Gdansk Assembly", "Poland"), ("Porto Foundry", "Portugal"),
         ("Brno Machining", "Czechia"), ("Lyon Systems", "France"), ("Bilbao Plant", "Spain"),
         ("Graz Electronics", "Austria"), ("Aarhus Service Centre", "Denmark")]
FIRST = ["Anna", "Mikael", "Sofia", "Jonas", "Elena", "Tomasz", "Ines", "Pavel", "Claire", "Marta", "Lukas",
         "Freja", "Otto", "Nadia", "Rafael", "Ida", "Kasper", "Lea", "Viktor", "Helena", "Matteo", "Zofia",
         "Emil", "Clara", "Aleksi", "Joana", "Henrik", "Petra", "Bruno", "Sanna"]
LAST = ["Virtanen", "Kowalski", "Ferreira", "Novak", "Moreau", "Etxeberria", "Huber", "Jensen", "Laine",
        "Wisniewski", "Costa", "Dvorak", "Lefevre", "Aguirre", "Gruber", "Nielsen", "Salo", "Zielinski",
        "Pereira", "Svoboda", "Girard", "Larsen", "Koskinen", "Mendes"]
SUP_A = ["Brightline", "Nordwave", "Ironpeak", "Silverfjord", "Bluecrest", "Redstone", "Clearwater", "Polaris",
         "Granite", "Evergreen", "Northgate", "Summit", "Keystone", "Harbour", "Falcon", "Meridian", "Oakridge",
         "Vantage", "Coastal", "Alpine"]
SUP_B = ["Castings", "Fasteners", "Seals", "Bearings", "Electronics", "Motors", "Polymers", "Steelworks",
         "Coatings", "Logistics"]
COUNTRIES = ["Germany", "Poland", "Italy", "Sweden", "Czechia", "Spain", "Netherlands", "Finland", "Portugal", "Austria"]


def _person(rng, used):
    while True:
        n = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        if n not in used:
            used.add(n)
            return n


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------
def _pdf_doc(path: Path, title: str, subtitle: str, pages: list[dict]):
    """pages: list of {heading, paragraphs[str], table: [[...]] | None}. One section per page."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.drawString(2 * cm, 1.2 * cm, f"{COMPANY} - {title} - CONFIDENTIAL (synthetic)")
        canvas.drawRightString(19 * cm, 1.2 * cm, f"Page {doc.page}")
        canvas.restoreState()

    story = []
    for i, pg in enumerate(pages):
        if i == 0:
            story += [Paragraph(title, styles["Title"]), Paragraph(subtitle, styles["Italic"]), Spacer(1, 12)]
        story.append(Paragraph(pg["heading"], styles["Heading2"]))
        for para in pg["paragraphs"]:
            story += [Paragraph(para, styles["BodyText"]), Spacer(1, 6)]
        if pg.get("table"):
            t = Table(pg["table"], hAlign="LEFT")
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                                   ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                                   ("FONTSIZE", (0, 0), (-1, -1), 9)]))
            story += [Spacer(1, 6), t, Spacer(1, 6)]
        for para in pg.get("after", []):
            story += [Paragraph(para, styles["BodyText"]), Spacer(1, 6)]
        if i < len(pages) - 1:
            story.append(PageBreak())
    SimpleDocTemplate(str(path), pagesize=A4, title=title, author=COMPANY).build(
        story, onFirstPage=footer, onLaterPages=footer)


def _prose_pdf(fb: FactBook, fname: str, title: str, subtitle: str, sections, topic: str):
    pages = []
    for pno, (heading, intro, facts) in enumerate(sections, start=1):
        paras = [intro] + [" ".join(s for s, _, _ in facts[i:i + 2]) for i in range(0, len(facts), 2)]
        pages.append({"heading": heading, "paragraphs": paras})
        for sentence, ans, qs in facts:
            fb.add(fname, pno, qs, ans, sentence, "pdf", topic)
    _pdf_doc(config.CORPUS_DIR / fname, title, subtitle, pages)


def _ops_report(fb: FactBook, rng: random.Random, used_names):
    fname = "HIS_Annual_Operations_Report_FY2025.pdf"
    pages = []
    summary = [("Group revenue for FY2025 was EUR 412.6 million, an increase of 6.3% on the prior year.", "EUR 412.6 million",
                ["What was group revenue in FY2025?", "How much revenue did the company report for fiscal 2025?"]),
               ("The adjusted EBITDA margin was 14.8%.", "14.8%",
                ["What was the adjusted EBITDA margin in FY2025?", "What EBITDA margin did the group achieve last fiscal year?"]),
               ("The group lost-time injury frequency rate (LTIFR) improved to 0.62 per million hours worked.", "0.62",
                ["What was the group LTIFR in FY2025?", "What lost-time injury frequency rate did the company report?"]),
               ("The order backlog at year end stood at EUR 188 million.", "EUR 188 million",
                ["What was the order backlog at the end of FY2025?", "How large was the year-end order backlog?"]),
               ("Capital expenditure totalled EUR 27.4 million, most of it on the Porto Foundry furnace upgrade.", "EUR 27.4 million",
                ["How much capital expenditure was spent in FY2025?", "What was total capex for the year?"])]
    pages.append({"heading": "1. Executive Summary",
                  "paragraphs": ["FY2025 was a year of steady growth despite volatile energy prices across Europe."]
                  + [s for s, _, _ in summary]})
    for s, a, q in summary:
        fb.add(fname, 1, q, a, s, "pdf", "operations")

    for i, (site, country) in enumerate(SITES, start=2):
        units = rng.randrange(8_000, 60_000, 10)
        otd = round(rng.uniform(86, 99), 1)
        lti = rng.randint(0, 9)
        mwh = rng.randrange(4_000, 40_000, 5)
        head = rng.randint(140, 900)
        director = _person(rng, used_names)
        table = [["Metric", "FY2025"], ["Units produced", f"{units:,}"], ["On-time delivery", f"{otd}%"],
                 ["Lost-time incidents", str(lti)], ["Energy consumption", f"{mwh:,} MWh"], ["Headcount", str(head)]]
        pages.append({"heading": f"{i}. Site Review: {site} ({country})",
                      "paragraphs": [f"The {site} site in {country} is led by site director {director}. "
                                     f"The table below summarises its key operating indicators for the fiscal year."],
                      "table": table,
                      "after": ["Improvement priorities for FY2026 include lean flow, energy efficiency and supplier quality."]})
        fb.add(fname, i, [f"How many units did {site} produce in FY2025?", f"What was the production output of the {site} site last year?", f"How many units came off the line at {site} during FY2025?"],
               f"{units:,}", f"{site} produced {units:,} units in FY2025.", "pdf", "operations")
        fb.add(fname, i, [f"What was the on-time delivery rate at {site}?", f"What percentage of {site} deliveries were on time in FY2025?", f"How reliable was {site} at shipping orders on schedule?"],
               f"{otd}%", f"{site} achieved {otd}% on-time delivery in FY2025.", "pdf", "operations")
        fb.add(fname, i, [f"How many lost-time incidents occurred at {site} in FY2025?", f"What was the number of lost-time incidents at the {site} site?", f"How many injuries causing time off work happened at {site}?"],
               str(lti), f"{site} recorded {lti} lost-time incidents in FY2025.", "pdf", "operations")
        fb.add(fname, i, [f"How much energy did {site} consume in FY2025?", f"What was the energy consumption of {site} in MWh?", f"What was the total energy use of {site} in FY2025?"],
               f"{mwh:,} MWh", f"{site} consumed {mwh:,} MWh of energy in FY2025.", "pdf", "operations")
        fb.add(fname, i, [f"Who is the site director of {site}?", f"Who leads the {site} site?", f"Who runs operations at {site}?"],
               director, f"The site director of {site} is {director}.", "pdf", "operations")
    _pdf_doc(config.CORPUS_DIR / fname, "Annual Operations Report FY2025", "Prepared by Group Operations", pages)


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------
PUMP_APPS = ["district heating circulation", "chemical dosing", "boiler feed water", "cooling tower circulation",
             "wastewater transfer", "irrigation", "fire protection", "food-grade transfer", "mining dewatering",
             "HVAC chilled water", "desalination pre-treatment", "pulp and paper stock transfer"]


def _pump_spec(fb: FactBook, rng: random.Random):
    from docx import Document

    fname = "HX_Pump_Series_Technical_Specification.docx"
    doc = Document()
    doc.add_heading("HX Centrifugal Pump Series - Technical Specification", 0)
    doc.add_paragraph(f"Document HX-TS-004 rev. C. Issued by {COMPANY} Product Engineering. This specification lists "
                      "the rated performance of every model in the HX series. Values apply at 50 Hz and 20 degC water.")
    apps = PUMP_APPS[:]
    rng.shuffle(apps)
    models = [f"HX-{n}" for n in (110, 140, 160, 200, 250, 280, 320, 360, 400, 450, 520, 600)]
    for i, model in enumerate(models):
        page = i + 2
        doc.add_page_break()
        flow = rng.randrange(80, 2400, 5)
        head = rng.randrange(12, 140)
        power = round(rng.uniform(1.1, 160.0), 1)
        impeller = rng.randrange(120, 520, 2)
        weight = rng.randrange(35, 1900)
        dn = rng.choice([32, 40, 50, 65, 80, 100, 125, 150, 200])
        temp = rng.choice([90, 105, 120, 140, 160])
        ip = rng.choice(["IP54", "IP55", "IP56", "IP65", "IP66"])
        app = apps[i]
        doc.add_heading(f"{i + 2}. {model} Centrifugal Pump", level=1)
        doc.add_paragraph(f"The {model} is recommended for {app} applications. It uses a closed impeller and a "
                          "mechanical shaft seal as standard.")
        rows = [("Maximum flow rate", f"{flow} L/min", "maximum flow rate", f"What is the most liquid the {model} can move per minute?"),
                ("Maximum head", f"{head} m", "maximum head", f"How high can the {model} lift water?"),
                ("Motor power", f"{power} kW", "motor power", f"How powerful is the motor fitted to the {model}?"),
                ("Impeller diameter", f"{impeller} mm", "impeller diameter", f"How wide is the impeller in the {model}?"),
                ("Dry weight", f"{weight} kg", "dry weight", f"How heavy is the {model} when empty?"),
                ("Inlet connection", f"DN{dn}", "inlet connection size", f"What size is the suction port on the {model}?"),
                ("Maximum fluid temperature", f"{temp} degC", "maximum fluid temperature", f"What is the hottest liquid the {model} can handle?"),
                ("Motor enclosure rating", ip, "motor enclosure (IP) rating", f"What ingress protection does the {model} motor have?")]
        table = doc.add_table(rows=1, cols=2)
        table.style = "Table Grid"
        table.rows[0].cells[0].text, table.rows[0].cells[1].text = "Parameter", "Value"
        for label, val, phrase, para in rows:
            r = table.add_row().cells
            r[0].text, r[1].text = label, val
            fb.add(fname, page, [f"What is the {phrase} of the {model} pump?", f"For the {model}, what is the {phrase}?",
                                 para], val, f"The {phrase} of the {model} is {val}.", "docx", "pumps")
        fb.add(fname, page, [f"What application is the {model} pump recommended for?", f"Which use case is the {model} designed for?"],
               app, f"The {model} is recommended for {app} applications.", "docx", "pumps")
    doc.save(config.CORPUS_DIR / fname)
    return models


def _firmware_spec(fb: FactBook, rng: random.Random):
    from docx import Document

    fname = "CU4_Controller_Firmware_Release_Notes.docx"
    doc = Document()
    doc.add_heading("CU-4 Pump Controller - Firmware Release Notes", 0)
    doc.add_paragraph("This document records every released firmware version for the CU-4 controller, including "
                      "default communication settings and safety parameters.")
    changes = ["added Modbus TCP support", "introduced dry-run protection", "added BACnet/IP gateway mode",
               "reduced boot time by 40 percent", "added secure boot with signed images", "introduced PID auto-tuning",
               "added OPC UA server", "fixed watchdog reset loop under high bus load", "added multi-pump cascade control",
               "introduced predictive bearing-wear alarm"]
    d = date(2023, 2, 6)
    for i in range(10):
        ver = f"4.{i}"
        page = i + 2
        d = d + timedelta(days=rng.randint(55, 110))
        wd = rng.choice([250, 500, 750, 1000, 1500, 2000])
        nodes = rng.choice([16, 24, 32, 48, 64, 96, 128])
        baud = rng.choice([9600, 19200, 38400, 57600, 115200])
        doc.add_page_break()
        doc.add_heading(f"{i + 2}. Firmware version {ver}", level=1)
        doc.add_paragraph(f"Firmware {ver} was released on {d.strftime('%d %B %Y')}. Key change: this version {changes[i]}.")
        doc.add_paragraph(f"In firmware {ver} the watchdog timeout is {wd} ms, the controller supports up to {nodes} "
                          f"fieldbus nodes, and the default RS-485 baud rate is {baud}.")
        ds = d.strftime("%d %B %Y")
        fb.add(fname, page, [f"When was CU-4 firmware {ver} released?", f"What is the release date of firmware version {ver}?"],
               ds, f"Firmware {ver} was released on {ds}.", "docx", "firmware")
        fb.add(fname, page, [f"What is the watchdog timeout in CU-4 firmware {ver}?", f"In firmware {ver}, how long is the watchdog timeout?"],
               f"{wd} ms", f"The watchdog timeout in firmware {ver} is {wd} ms.", "docx", "firmware")
        fb.add(fname, page, [f"How many fieldbus nodes does firmware {ver} support?", f"What is the maximum number of fieldbus nodes in CU-4 firmware {ver}?"],
               str(nodes), f"Firmware {ver} supports up to {nodes} fieldbus nodes.", "docx", "firmware")
        fb.add(fname, page, [f"What is the default RS-485 baud rate in firmware {ver}?", f"Which baud rate does CU-4 firmware {ver} use by default?"],
               str(baud), f"The default RS-485 baud rate in firmware {ver} is {baud}.", "docx", "firmware")
        fb.add(fname, page, [f"What was the key change in CU-4 firmware {ver}?", f"What did firmware version {ver} introduce?"],
               changes[i], f"Firmware {ver} {changes[i]}.", "docx", "firmware")
    doc.save(config.CORPUS_DIR / fname)


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
def _suppliers(fb: FactBook, rng: random.Random):
    fname = "supplier_register.csv"
    names = set()
    while len(names) < 40:
        names.add(f"{rng.choice(SUP_A)} {rng.choice(SUP_B)}")
    rows = []
    for i, name in enumerate(sorted(names, key=lambda _: rng.random()), start=1):
        sid = f"S-{1000 + i}"
        cat = name.split()[-1]
        country = rng.choice(COUNTRIES)
        lead = rng.randrange(7, 120)
        score = rng.randrange(55, 100)
        exp = date(2026, 1, 1) + timedelta(days=rng.randrange(0, 1100))
        rows.append([sid, name, country, cat, lead, score, exp.isoformat()])
        fb.add(fname, i, [f"What is the lead time for {name}?", f"How many days lead time does supplier {name} have?", f"How long does {name} take to deliver after we place an order?"],
               str(lead), f"The lead time for {name} is {lead} days.", "csv", "suppliers")
        fb.add(fname, i, [f"What is the quality score of {name}?", f"Which quality score does supplier {name} have?", f"How does {name} rate on quality in the supplier register?"],
               str(score), f"{name} has a quality score of {score}.", "csv", "suppliers")
        fb.add(fname, i, [f"When does the contract with {name} expire?", f"What is the contract expiry date for {name}?", f"Until when are we contracted with {name}?"],
               exp.isoformat(), f"The contract with {name} expires on {exp.isoformat()}.", "csv", "suppliers")
        fb.add(fname, i, [f"In which country is {name} based?", f"Where is supplier {name} located?", f"Which country does {name} operate from?"],
               country, f"{name} is based in {country}.", "csv", "suppliers")
    with open(config.CORPUS_DIR / fname, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["supplier_id", "supplier_name", "country", "category", "lead_time_days", "quality_score", "contract_expiry"])
        w.writerows(rows)
    return [r[1] for r in rows]


ASSETS = ["Hydraulic press 250t", "CNC lathe", "5-axis machining centre", "Induction furnace", "Paint booth",
          "Air compressor", "Overhead crane 10t", "Pump test rig", "Robotic welding cell", "Laser cutter",
          "Coordinate measuring machine", "Forklift truck", "Wave soldering machine", "Shot blasting cabinet"]


def _maintenance(fb: FactBook, rng: random.Random, used_names):
    fname = "equipment_maintenance_schedule.csv"
    techs = [_person(rng, used_names) for _ in range(12)]
    rows = []
    ids = rng.sample(range(2000, 2999), 40)
    for i, n in enumerate(ids, start=1):
        aid = f"AST-{n}"
        desc = rng.choice(ASSETS)
        site = rng.choice(SITES)[0]
        interval = rng.choice([30, 45, 60, 90, 120, 180, 365])
        last = date(2026, 1, 1) + timedelta(days=rng.randrange(0, 240))
        tech = rng.choice(techs)
        rows.append([aid, desc, site, interval, last.isoformat(), tech])
        fb.add(fname, i, [f"What is the maintenance interval for asset {aid}?", f"How often is {aid} serviced?", f"How many days are there between scheduled services of {aid}?"],
               str(interval), f"Asset {aid} ({desc}) is serviced every {interval} days.", "csv", "maintenance")
        fb.add(fname, i, [f"When was asset {aid} last serviced?", f"What is the last service date of {aid}?", f"When did {aid} last receive scheduled maintenance?"],
               last.isoformat(), f"Asset {aid} was last serviced on {last.isoformat()}.", "csv", "maintenance")
        fb.add(fname, i, [f"Which technician is assigned to asset {aid}?", f"Who maintains equipment {aid}?", f"Who is the responsible technician for {aid} in the maintenance schedule?"],
               tech, f"The technician assigned to {aid} is {tech}.", "csv", "maintenance")
    with open(config.CORPUS_DIR / fname, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["asset_id", "description", "site", "service_interval_days", "last_service_date", "assigned_technician"])
        w.writerows(rows)
    return rows, techs


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------
def _incidents(fb: FactBook, rng: random.Random, used_names):
    fname = "incident_postmortems.md"
    systems = ["ERP order service", "MES production scheduler", "Customer portal", "VPN gateway", "Email relay",
               "Warehouse scanner network", "Payroll batch", "Pump telemetry ingestion", "Identity provider", "Backup cluster"]
    causes = ["an expired TLS certificate", "a full transaction-log disk", "a misconfigured firewall rule",
              "a faulty network switch firmware update", "a database connection-pool leak", "a DNS record deleted during cleanup",
              "an unindexed query introduced in a release", "a power supply failure in rack B4",
              "a clock drift on the primary domain controller", "an exhausted cloud API quota"]
    lines = ["# Incident Post-Mortems 2025", "",
             f"Blameless post-mortem summaries for major IT incidents at {COMPANY}.", ""]
    d = date(2025, 1, 10)
    for i in range(10):
        sec = i + 1
        d = d + timedelta(days=rng.randint(15, 40))
        iid = f"INC-2025-{rng.randint(100, 999)}"
        sev = rng.choice(["SEV1", "SEV2", "SEV3"])
        dur = rng.randrange(18, 600)
        owner = _person(rng, used_names)
        lines += [f"## {iid}: {systems[i]} outage", "",
                  f"- **Date:** {d.isoformat()}", f"- **Severity:** {sev}", f"- **Duration:** {dur} minutes",
                  f"- **Root cause:** {causes[i]}", f"- **Corrective action owner:** {owner}", "",
                  f"The {systems[i]} was unavailable for {dur} minutes. The root cause was {causes[i]}. "
                  "Monitoring alerts were added and the runbook was updated.", ""]
        q = lambda a, b: [a, b]
        fb.add(fname, sec, q(f"When did incident {iid} occur?", f"On what date did the {systems[i]} outage ({iid}) happen?"),
               d.isoformat(), f"Incident {iid} occurred on {d.isoformat()}.", "md", "incidents")
        fb.add(fname, sec, q(f"What severity was incident {iid}?", f"How severe was the {systems[i]} outage?"),
               sev, f"Incident {iid} was classified {sev}.", "md", "incidents")
        fb.add(fname, sec, q(f"How long did incident {iid} last?", f"What was the duration of the {systems[i]} outage?"),
               f"{dur} minutes", f"Incident {iid} lasted {dur} minutes.", "md", "incidents")
        fb.add(fname, sec, q(f"What was the root cause of incident {iid}?", f"What caused the {systems[i]} outage?"),
               causes[i], f"The root cause of {iid} was {causes[i]}.", "md", "incidents")
        fb.add(fname, sec, q(f"Who owns the corrective action for incident {iid}?", f"Who is responsible for corrective actions after the {systems[i]} outage?"),
               owner, f"The corrective action owner for {iid} is {owner}.", "md", "incidents")
    (config.CORPUS_DIR / fname).write_text("\n".join(lines))


def _meetings(fb: FactBook, rng: random.Random, used_names):
    fname = "engineering_meeting_notes.md"
    topics = [("HX-700 development", "approved a development budget of EUR 1.2 million", "EUR 1.2 million",
               "What development budget was approved for the HX-700?"),
              ("Test lab expansion", "selected Polaris Electronics as the data-acquisition vendor", "Polaris Electronics",
               "Which vendor was selected for test lab data acquisition?"),
              ("CU-5 controller concept", "set the CU-5 prototype deadline to 15 May 2026", "15 May 2026",
               "What is the deadline for the CU-5 prototype?"),
              ("Seal supplier dual-sourcing", "agreed to qualify a second mechanical seal supplier by Q3 2026", "Q3 2026",
               "By when must a second mechanical seal supplier be qualified?"),
              ("Simulation tooling", "decided to standardise on OpenFOAM for CFD simulation", "OpenFOAM",
               "Which CFD tool did engineering standardise on?"),
              ("Design review cadence", "decided that design reviews will be held every 3 weeks", "every 3 weeks",
               "How often will engineering design reviews be held?"),
              ("Energy efficiency target", "set a target of IE5 motor efficiency for all new pumps", "IE5",
               "What motor efficiency class is targeted for new pumps?"),
              ("Field failure analysis", "assigned the HX-320 bearing failure investigation to the reliability team", "reliability team",
               "Which team investigates the HX-320 bearing failures?")]
    lines = ["# Engineering Leadership Meeting Notes", "",
             "Minutes of the monthly engineering leadership meeting. Contact details are included for follow-up.", ""]
    d = date(2025, 9, 3)
    for i, (topic, decision, ans, question) in enumerate(topics):
        sec = i + 1
        d = d + timedelta(days=28)
        chair = _person(rng, used_names)
        email = chair.lower().replace(" ", ".") + "@halvorsen-is.example"
        phone = f"+358 40 {rng.randint(100, 999)} {rng.randint(1000, 9999)}"
        attendees = rng.randint(6, 14)
        lines += [f"## {d.isoformat()} - {topic}", "",
                  f"Chair: {chair} ({email}, {phone}). Attendees: {attendees}.", "",
                  f"Decision: the committee {decision}.", "",
                  "Action items were recorded in the engineering tracker.", ""]
        fb.add(fname, sec, [question, f"What did the {d.strftime('%B %Y')} engineering meeting decide about {topic.lower()}?"],
               ans, f"The committee {decision}.", "md", "meetings")
        fb.add(fname, sec, [f"Who chaired the engineering meeting on {topic.lower()}?", f"Who was the chair of the {d.isoformat()} engineering meeting?"],
               chair, f"The meeting on {topic.lower()} was chaired by {chair}.", "md", "meetings")
        fb.add(fname, sec, [f"How many people attended the engineering meeting on {topic.lower()}?", f"What was the attendance at the {d.isoformat()} engineering leadership meeting?"],
               str(attendees), f"{attendees} people attended the meeting on {topic.lower()}.", "md", "meetings")
    (config.CORPUS_DIR / fname).write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# "Hard-negative" documents: they mention the same entities (sites, suppliers,
# pump models, assets, firmware versions) in a different context, so lexical or
# entity overlap alone is not enough to find the right evidence.
# ---------------------------------------------------------------------------
MEASURES = ["compressed-air leak repairs", "furnace heat recovery", "LED lighting retrofits", "variable-speed drives on fans",
            "a new building management system", "process cooling optimisation", "weekend shutdown discipline", "boiler replacement"]


def _energy_review(fb: FactBook, rng: random.Random, used_names):
    fname = "HIS_Site_Energy_and_Sustainability_Review_2025.pdf"
    measures = MEASURES[:]
    rng.shuffle(measures)
    pages = [{"heading": "1. Introduction",
              "paragraphs": ["This review summarises energy-saving projects and emissions at each manufacturing site. "
                             "Absolute consumption figures are reported in the Annual Operations Report; this document "
                             "reports savings and renewable capacity only."]}]
    for i, (site, country) in enumerate(SITES, start=2):
        sav = rng.randrange(300, 3_000, 5)
        pct = round(rng.uniform(2.0, 14.0), 1)
        kwp = rng.randrange(80, 1_400, 10)
        co2 = rng.randrange(900, 16_000, 10)
        mgr = _person(rng, used_names)
        pages.append({"heading": f"{i}. {site} ({country})", "paragraphs": [
            f"{site} reduced its energy consumption by {sav:,} MWh ({pct}%) compared with FY2024, mainly through {measures[i - 2]}.",
            f"Rooftop solar capacity at {site} reached {kwp:,} kWp. Scope 2 emissions for the site were {co2:,} tonnes CO2e.",
            f"The energy manager responsible for {site} is {mgr}."]})
        fb.add(fname, i, [f"How much did {site} reduce its energy consumption by?", f"What energy savings did {site} achieve versus FY2024?"],
               f"{sav:,} MWh", f"{site} reduced its energy consumption by {sav:,} MWh.", "pdf", "energy")
        fb.add(fname, i, [f"What is the rooftop solar capacity at {site}?", f"How many kWp of solar are installed at {site}?"],
               f"{kwp:,} kWp", f"Rooftop solar capacity at {site} is {kwp:,} kWp.", "pdf", "energy")
        fb.add(fname, i, [f"What were the Scope 2 emissions of {site}?", f"How many tonnes CO2e of Scope 2 emissions did {site} report?"],
               f"{co2:,} tonnes", f"Scope 2 emissions at {site} were {co2:,} tonnes CO2e.", "pdf", "energy")
        fb.add(fname, i, [f"Who is the energy manager at {site}?", f"Who is responsible for energy management at {site}?"],
               mgr, f"The energy manager for {site} is {mgr}.", "pdf", "energy")
        fb.add(fname, i, [f"What was the main energy-saving measure at {site}?", f"How did {site} achieve its energy savings?"],
               measures[i - 2], f"{site} saved energy mainly through {measures[i - 2]}.", "pdf", "energy")
    _pdf_doc(config.CORPUS_DIR / fname, "Site Energy and Sustainability Review 2025", "Group EHS", pages)


def _supplier_audits(fb: FactBook, rng: random.Random, suppliers: list[str], used_names):
    fname = "Supplier_Audit_Report_2025.pdf"
    auditors = [_person(rng, used_names) for _ in range(5)]
    pages = []
    for p, start in enumerate(range(0, len(suppliers), 10), start=1):
        table = [["Supplier", "Audit date", "Audit score", "Major findings", "Lead auditor"]]
        for name in suppliers[start:start + 10]:
            d = (date(2025, 1, 6) + timedelta(days=rng.randrange(0, 340))).isoformat()
            score, majors, aud = rng.randrange(52, 99), rng.randint(0, 6), rng.choice(auditors)
            table.append([name, d, str(score), str(majors), aud])
            fb.add(fname, p, [f"When was {name} audited in 2025?", f"What was the audit date for {name}?"],
                   d, f"{name} was audited on {d}.", "pdf", "supplier_audit")
            fb.add(fname, p, [f"What audit score did {name} receive in the 2025 supplier audit?", f"How did {name} score in its 2025 audit?"],
                   str(score), f"{name} received an audit score of {score}.", "pdf", "supplier_audit")
            fb.add(fname, p, [f"How many major findings were raised in the {name} audit?", f"How many major nonconformities did the auditors find at {name}?"],
                   str(majors), f"The {name} audit raised {majors} major findings.", "pdf", "supplier_audit")
            fb.add(fname, p, [f"Who led the 2025 audit of {name}?", f"Which auditor was the lead auditor for {name}?"],
                   aud, f"The lead auditor for {name} was {aud}.", "pdf", "supplier_audit")
        pages.append({"heading": f"{p}. Audit results (group {p})",
                      "paragraphs": ["Audit scores below reflect the on-site process audit and are independent of the "
                                     "quality score held in the supplier register."], "table": table})
    _pdf_doc(config.CORPUS_DIR / fname, "Supplier Audit Report 2025", "Supplier Quality", pages)


def _selection_guide(fb: FactBook, rng: random.Random, models: list[str]):
    fname = "HX_Pump_Selection_Guide.md"
    lines = ["# HX Pump Selection Guide", "",
             "Guidance for sales engineers. Duty points below are typical operating points, not maximum ratings; "
             "see the technical specification for rated limits.", ""]
    for sec, model in enumerate(models, start=1):
        f2, h2 = rng.randrange(40, 1200, 5), rng.randrange(8, 90)
        eff = round(rng.uniform(62, 86), 1)
        kit = f"SK-{model.split('-')[1]}-{rng.choice('ABCDE')}"
        legacy = f"HX-{int(model.split('-')[1]) - rng.choice([5, 10, 15])}L"
        lines += [f"## {model}", "",
                  f"Typical duty point: {f2} L/min at {h2} m head. Best efficiency at the duty point is {eff}%.", "",
                  f"Recommended spare-parts kit: {kit}. The {model} replaces the legacy model {legacy}.", ""]
        fb.add(fname, sec, [f"What is the typical duty point flow of the {model}?", f"At what flow does the {model} typically operate?"],
               f"{f2} L/min", f"The typical duty point of the {model} is {f2} L/min at {h2} m head.", "md", "selection")
        fb.add(fname, sec, [f"What is the best efficiency of the {model} at its duty point?", f"How efficient is the {model} at its typical duty point?"],
               f"{eff}%", f"The {model} reaches {eff}% efficiency at its duty point.", "md", "selection")
        fb.add(fname, sec, [f"Which spare-parts kit is recommended for the {model}?", f"What spare kit should be ordered for the {model}?"],
               kit, f"The recommended spare-parts kit for the {model} is {kit}.", "md", "selection")
        fb.add(fname, sec, [f"Which legacy model does the {model} replace?", f"What older pump is superseded by the {model}?"],
               legacy, f"The {model} replaces the legacy model {legacy}.", "md", "selection")
    (config.CORPUS_DIR / fname).write_text("\n".join(lines))


def _work_orders(fb: FactBook, rng: random.Random, assets, techs):
    fname = "maintenance_work_orders_2026.csv"
    types = ["corrective repair", "preventive service", "calibration", "safety inspection", "lubrication", "sensor replacement"]
    rows = []
    for i in range(1, 61):
        a = rng.choice(assets)
        wo = f"WO-{26100 + i * 7 + rng.randrange(0, 7)}"
        d = (date(2026, 1, 2) + timedelta(days=rng.randrange(0, 250))).isoformat()
        typ, tech, hrs = rng.choice(types), rng.choice(techs), round(rng.uniform(0.5, 14.0), 1)
        rows.append([wo, a[0], d, typ, tech, hrs])
        fb.add(fname, i, [f"How many labour hours were booked on work order {wo}?", f"What was the labour time for {wo}?"],
               str(hrs), f"Work order {wo} booked {hrs} labour hours.", "csv", "work_orders")
        fb.add(fname, i, [f"What type of work was done under work order {wo}?", f"What kind of job was {wo}?"],
               typ, f"Work order {wo} was a {typ}.", "csv", "work_orders")
        fb.add(fname, i, [f"Which technician completed work order {wo}?", f"Who carried out {wo}?"],
               tech, f"Work order {wo} was completed by {tech}.", "csv", "work_orders")
    with open(config.CORPUS_DIR / fname, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["work_order_id", "asset_id", "completed_date", "work_type", "technician", "labour_hours"])
        w.writerows(rows)


def _known_issues(fb: FactBook, rng: random.Random):
    fname = "CU4_Known_Issues.md"
    issues = ["Modbus registers above 40000 return stale values", "display freezes after 49 days of uptime",
              "BACnet device ID resets after power loss", "cascade mode ignores the standby pump",
              "OPC UA certificates expire after 365 days", "PID auto-tune overshoots on small loops",
              "alarm log truncates at 500 entries", "firmware update fails on 8 GB SD cards"]
    lines = ["# CU-4 Controller Known Issues", "",
             "Open and resolved defects affecting released CU-4 firmware. See the release notes for feature changes.", ""]
    for sec, i in enumerate(range(8), start=1):
        ver = f"4.{i + 1}"
        fixed = f"4.{i + 2}"
        lines += [f"## Issue CU4-KI-{101 + i} (affects firmware {ver})", "",
                  f"Symptom: {issues[i]}. Workaround: restart the controller during the next maintenance window. "
                  f"Resolved in firmware {fixed}.", ""]
        fb.add(fname, sec, [f"What known issue affects CU-4 firmware {ver}?", f"Which defect was reported in firmware {ver}?"],
               issues[i], f"Firmware {ver} has a known issue: {issues[i]}.", "md", "known_issues")
        fb.add(fname, sec, [f"In which firmware version was issue CU4-KI-{101 + i} fixed?", f"Which release resolved CU4-KI-{101 + i}?"],
               fixed, f"Issue CU4-KI-{101 + i} was resolved in firmware {fixed}.", "md", "known_issues")
    (config.CORPUS_DIR / fname).write_text("\n".join(lines))


# Questions the corpus deliberately cannot answer (used to test refusals).
UNANSWERABLE = [
    "What is the CEO's annual salary?",
    "What is the maximum flow rate of the HX-990 pump?",
    "How many days of paternity leave does the secondary caregiver receive?",
    "What was group revenue in FY2019?",
    "What is the stock ticker symbol of Halvorsen Industrial Systems?",
    "Which supplier provides titanium impellers?",
    "What is the watchdog timeout in CU-4 firmware 5.2?",
    "How many units did the Oslo site produce in FY2025?",
    "What is the company's policy on cryptocurrency investments?",
    "Who won the 2025 internal hackathon?",
    "What is the noise level in decibels of the HX-140 pump?",
    "What is the per diem for travel to the moon?",
    "Which ISO 14001 certificate number does the company hold?",
    "What was the root cause of incident INC-2024-001?",
    "How many parking spaces are available at Tampere Works?",
    "What is the dress code for the Lyon office?",
    "What is the pension contribution percentage?",
    "When was firmware 3.9 released?",
    "What is the lead time for Acme Widgets?",
    "How many vacation days do interns get?",
]


def build_corpus(n_test: int = 200, seed: int = config.SEED) -> dict:
    rng = random.Random(seed)
    fb = FactBook()
    used = set()
    for old in config.CORPUS_DIR.iterdir():
        old.unlink()
    _prose_pdf(fb, "HIS_Employee_Handbook_2026.pdf", "Employee Handbook 2026", "People Operations", HANDBOOK, "hr_policy")
    _ops_report(fb, rng, used)
    _prose_pdf(fb, "HIS_Quality_Compliance_Manual.pdf", "Quality and Compliance Manual", "Quality Department rev. 7",
               COMPLIANCE, "quality")
    models = _pump_spec(fb, rng)
    _firmware_spec(fb, rng)
    suppliers = _suppliers(fb, rng)
    assets, techs = _maintenance(fb, rng, used)
    _incidents(fb, rng, used)
    _meetings(fb, rng, used)
    # hard-negative documents
    _energy_review(fb, rng, used)
    _supplier_audits(fb, rng, suppliers, used)
    _selection_guide(fb, rng, models)
    _work_orders(fb, rng, assets, techs)
    _known_issues(fb, rng)

    # Stratified held-out test split (by document) -- facts in the test split never
    # appear in reranker training data.
    quota = {"HIS_Employee_Handbook_2026.pdf": 18, "HIS_Annual_Operations_Report_FY2025.pdf": 20,
             "HIS_Quality_Compliance_Manual.pdf": 12, "HX_Pump_Series_Technical_Specification.docx": 28,
             "CU4_Controller_Firmware_Release_Notes.docx": 16, "supplier_register.csv": 22,
             "equipment_maintenance_schedule.csv": 18, "incident_postmortems.md": 12,
             "engineering_meeting_notes.md": 10, "HIS_Site_Energy_and_Sustainability_Review_2025.pdf": 10,
             "Supplier_Audit_Report_2025.pdf": 12, "HX_Pump_Selection_Guide.md": 10,
             "maintenance_work_orders_2026.csv": 8, "CU4_Known_Issues.md": 4}
    assert sum(quota.values()) == n_test
    test, train = [], []
    by_doc: dict[str, list[Fact]] = {}
    for f in fb.facts:
        by_doc.setdefault(f.doc, []).append(f)
    for doc, facts in by_doc.items():
        pick = set(id(x) for x in rng.sample(facts, quota[doc]))
        for f in facts:
            (test if id(f) in pick else train).append(f)

    def qa_row(f: Fact, q: str, split: str):
        return {"qid": f"{f.fact_id}-{split}", "question": q, "answer": f.answer, "ground_truth": f.gold_answer,
                "doc": f.doc, "page": f.page, "doc_type": f.doc_type, "topic": f.topic, "fact_id": f.fact_id}

    test_rows = [qa_row(f, rng.choice(f.questions), "test") for f in test]
    train_rows = [dict(qa_row(f, q, "train"), qid=f"{f.fact_id}-train{j}") for f in train for j, q in enumerate(f.questions)]
    unans = [{"qid": f"U{i:03d}", "question": q, "answer": None, "doc": None, "page": None}
             for i, q in enumerate(UNANSWERABLE, 1)]

    _dump(config.EVAL_DIR / "facts.jsonl", [asdict(f) for f in fb.facts])
    _dump(config.EVAL_DIR / "test_qa.jsonl", test_rows)
    _dump(config.EVAL_DIR / "train_qa.jsonl", train_rows)
    _dump(config.EVAL_DIR / "unanswerable_qa.jsonl", unans)
    return {"documents": sorted(p.name for p in config.CORPUS_DIR.iterdir()), "facts": len(fb.facts),
            "test_pairs": len(test_rows), "train_pairs": len(train_rows), "train_facts": len(train),
            "unanswerable": len(unans)}


def _dump(path: Path, rows):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def load_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]
