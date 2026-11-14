"""Turns the failed tests in pytest's junit xml into GitHub annotations (the CI log is hard to open; annotations show on the run page)."""
import sys
import xml.etree.ElementTree as ET

for path in sys.argv[1:]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as e:
        print(f"::error title=no test report::{e}")
        continue
    for case in root.iter("testcase"):
        for bad in list(case.findall("failure")) + list(case.findall("error")):
            msg = " ".join(((bad.get("message") or "") + " " + (bad.text or "")[-700:]).split())[:900].replace("%", "%25")
            print(f"::error title=FAILED {case.get('classname')}.{case.get('name')}::{msg}")
