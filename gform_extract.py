import json
import sys

import requests
from bs4 import BeautifulSoup

if __name__ == "__main__":
    if len(sys.argv) <= 1:
        sys.exit(
            "Need a google form url as input"
        )

    url = sys.argv[1]

    if "docs.google.com/forms/" not in url:
        sys.exit("Not supported URL")

    form_url = url
    form_url = form_url.rsplit("/", 1)[0] + "/formResponse?"

    if "https://" not in form_url:
        form_url = "https://" + form_url

    response = requests.get(form_url)

    soup = BeautifulSoup(response.text, "html.parser")

    form = soup.find("div", attrs={"class": "freebirdFormviewerViewItemList"})

    entries = {}
    text_inputs = form.findAll("input", attrs={"type": "text"})
    for ti in text_inputs:
        if ti.get("name"):
            entries[ti.get("name")] = "text"

    hidden_inputs = form.findAll("input", attrs={"type": "hidden"})

    for hi in hidden_inputs:
        if hi.get("name"):
            entries[hi.get("name")] = "hidden"

    text_areas = soup.findAll("textarea")

    for ta in text_areas:
        if ta.get("name"):
            entries[ta.get("name")] = "text"

    print("found this ", entries)

    # TODO parse check box entries for options

    with open("form.json", "w") as fp:
        json.dump({"entries": entries}, fp)
