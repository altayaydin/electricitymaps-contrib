#!/usr/bin/env python3
import re
from datetime import datetime
from io import BytesIO
from logging import Logger, getLogger
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from PIL import Image
from pytesseract import image_to_string

# The request library is used to fetch content through HTTP
from requests import Session

from .JP import fetch_production as jp_fetch_production

# please try to write PEP8 compliant code (use a linter). One of PEP8's
# requirement is to limit your line length to 79 characters.

TIMEZONE = ZoneInfo("Asia/Tokyo")


def fetch_production(
    zone_key: str = "JP-KN",
    session: Session | None = None,
    target_datetime: datetime | None = None,
    logger: Logger = getLogger(__name__),
):
    """
    This method adds nuclear production on top of the solar data returned by the JP parser.
    It tries to match the solar data with the nuclear data.
    If there is a difference of more than 30 minutes between solar and nuclear data, the method will fail.
    """
    session = session or Session()
    if target_datetime is not None:
        raise NotImplementedError("This parser can only fetch live data")

    jp_data = jp_fetch_production(zone_key, session, target_datetime, logger)
    nuclear_mw, nuclear_datetime = get_nuclear_production()
    latest = jp_data[
        -1
    ]  # latest solar data is the most likely to fit with nuclear production
    diff = None
    if nuclear_datetime > latest["datetime"]:
        diff = nuclear_datetime - latest["datetime"]
    else:
        diff = latest["datetime"] - nuclear_datetime
    if abs(diff.seconds) > 30 * 60:
        raise Exception("Difference between nuclear datetime and JP data is too large")

    latest["production"]["nuclear"] = nuclear_mw
    latest["production"]["unknown"] = latest["production"]["unknown"] - nuclear_mw
    return latest


URL = (
    "https://www.kepco.co.jp/energy_supply/energy/nuclear_power/info/monitor/live_unten"
)
IMAGE_CORE_URL = "https://www.kepco.co.jp/"


def get_image_text(img_url, lang, width=None):
    """
    Fetches image based on URL, crops it and extract text from the image.
    """
    r = Request(img_url, headers={"User-Agent": "Mozilla/5.0"})
    img_bytes = urlopen(r).read()
    img = Image.open(BytesIO(img_bytes))
    height = img.size[1]

    if width is None:
        width = 160

    img = img.crop((0, int(height / 8), width, height))
    # cropping the image, makes it easier to read for tesseract
    text = image_to_string(img, lang=lang)
    return text


def extract_capacity(tr):
    """
    The capacity for each unit has the class "list03".
    and it uses the chinese symbol for 10k(万).
    If this changes, the method will become inaccurate.
    """
    td = tr.findAll("td", {"class": "list03"})
    if len(td) == 0:
        return None
    raw_text = td[0].getText()
    kw_energy = raw_text.split("万")[0]
    return float(kw_energy) * 10000


def extract_operation_percentage(tr):
    """Operation percentage is located on images of type .gif"""
    td = tr.findAll("img")
    if len(td) == 0:
        return None
    img = td[0]
    url = IMAGE_CORE_URL + img["src"]
    if ".gif" in url:
        text = get_image_text(url, "eng", width=65)
        # will return a number and percentage eg ("104%"). Sometimes a little more eg: ("104% 4...")
        split = text.split("%")
        if len(split) == 0:
            return None
        return float(split[0]) / 100
    else:
        return None


def extract_time(soup):
    """
    Time is located in an image.
    Decipher the text containing the data and assumes there will only be 4 digits making up the datetime.
    """
    img_relative = soup.findAll("img", {"class": "time-data"})[0]["src"]
    img_url_full = IMAGE_CORE_URL + img_relative
    text = get_image_text(img_url_full, "jpn")
    digits = re.findall(r"\d+", text)
    digits = [int(x) for x in digits]
    if len(digits) != 4:
        # something went wrong while extracting time from Japan
        raise Exception("Something went wrong while extracting local time")

    nuclear_datetime = datetime.now(tz=TIMEZONE).replace(
        month=digits[0],
        day=digits[1],
        hour=digits[2],
        minute=digits[3],
        second=0,
        microsecond=0,
    )
    return nuclear_datetime


def get_nuclear_production():
    """
    Fetches all the rows that contains data of nuclear units and calculates the total kw generated by all plants.
    Illogically, all the rows has the class "mihama_realtime" which they might fix in the future.
    """
    r = Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    html = urlopen(r).read()
    soup = BeautifulSoup(html, "html.parser")

    nuclear_datetime = extract_time(soup)
    _rows = soup.findAll(
        "tr", {"class": "mihama_realtime"}
    )  # TODO: Should we just remove this?
    tr_list = soup.findAll("tr")

    total_kw = 0
    for tr in tr_list:
        capacity = extract_capacity(tr)
        operation_percentage = extract_operation_percentage(tr)
        if capacity is None or operation_percentage is None:
            continue
        kw = capacity * operation_percentage
        total_kw = total_kw + kw
    nuclear_mw = total_kw / 1000.0  # convert to mw

    return nuclear_mw, nuclear_datetime


if __name__ == "__main__":
    """Main method, never used by the Electricity Map backend, but handy for testing."""

    print("fetch_production() ->")
    print(fetch_production())
