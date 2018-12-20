# -*- coding: utf-8 -*-

import logging
import random
import re
import string
import sys
import threading
import time
from queue import PriorityQueue, Empty, Full
from threading import Thread
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup
from newspaper import Article, ArticleException

from .exceptions import ExceptionHttpStatusCode, ExceptionThreadDied
from .log import *
from .scaper import Kolouri

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s (%(threadName)-10s) [%(levelname)-5.5s]  %(message)s",
                    datefmt='%Y-%m-%d %H:%M:%S', )

logging.getLogger(__name__)

MEM_SIZE = 1024  # queue max size

SYNC_SLEEP = 60  # sleep time intervals for threads
STEP_SLEEP = 2
POST_SLEEP = 2
MAIN_SLEEP = 2
UPDATE_SLEEP = 30

GROUP_URL = "https://www.facebook.com/pg/TUCSecrets/about/"
TARGET_URL = "https://docs.google.com/forms/d/e/1FAIpQLSedrGe0vpdK2FfwdpMTU1VUl8AEuYquC8UeH4atA66hUA5TRQ/viewform"
TARGET_URL = TARGET_URL.rsplit("/", 1)[0] + "/formResponse?"

urlLock = threading.Lock()  # shared lock for TARGET_URL

form_metadata = {'school': 'entry.1328574731',  # make up friendly names for form attributes
                 'nickname': 'entry.1373873555',
                 'secret': 'entry.1383662701',
                 'email': 'emailAddress'
                 }

metadataLock = threading.Lock()  # shared lock for form_metadata


def httpRequest(url):
    response = None
    try:
        response = requests.get(url)

        if response.status_code != 200:
            raise ExceptionHttpStatusCode("requests received {} status code GET/ {}".format(response.status_code, url))
    except requests.exceptions.RequestException as e:
        logging.error(e)
    except ExceptionHttpStatusCode as e:
        logging.warning(e)
    finally:
        if response.text:
            return response.text


def scapePage(url, pageScraper):
    raw_html = httpRequest(url)

    if raw_html:
        p = pageScraper(raw_html)
        return p.scrape()
    logging.warning("scraped page is empty")


def extractContent(url, lang='el'):
    article = None
    try:
        article = Article(url, language=lang)
        article.download()
        article.parse()
    except ArticleException as e:
        logging.warning(e)

    if article:
        text = article.text.strip()
        return text, len(text)


def check_for_updates(queue, target_url):
    while True:
        urls = scapePage(target_url, Kolouri)
        logging.info("found {} urls".format(len(urls)))

        for url in urls:
            try:
                text, size = extractContent(url)
            except ArticleException as e:
                logging.warning("no data {}".format(str(url)))
            except Exception as e:
                logging.info(e)
            else:
                sentences = text.split('.')
                for sentence in sentences:
                    if re.search("κουλούρι", sentence, re.IGNORECASE):
                        continue

                    priority = random.randint(1, MEM_SIZE)
                    try:
                        queue.put((priority, sentence), block=False)
                    except Full:
                        logging.warning("text queue is full, waiting 30 sec")
                        time.sleep(30)

                logging.info("added {} messages to queue".format(len(sentences)))
        time.sleep(UPDATE_SLEEP)


def post_secret(queue, total_counter, ack_counter):
    try:
        with open('names.txt', 'rb') as file:
            names = file.readlines()
    except FileNotFoundError:
        return

    # make pretty names
    names = [name.decode('utf-8') for name in names]
    names = [name[0].capitalize() + name[1:].lower() for name in names]

    schools = ["ΜΠΔ", "ΗΜΜΥ", "ΑΡΜΗΧ", "ΜΗΧΟΠ", "ΜΗΠΕΡ"]

    while True:
        try:
            secret = queue.get(block=False)
        except Empty:
            logging.warning("deque failed, queue empty! sleep for 10 sec")
            time.sleep(10)
            continue
        else:
            # make up random form data

            email_entry = "".join(random.choices(string.ascii_uppercase + string.digits, k=5)) + "@yahoo.com"
            school_entry = random.choice(schools)
            nickname_entry = random.choice(names)
            secret_entry = secret[1]

            form_data = {form_metadata['school']: school_entry,
                         form_metadata['nickname']: nickname_entry,
                         form_metadata['secret']: secret_entry,
                         form_metadata['email']: email_entry
                         }

            try:
                total_counter.count()
                with urlLock:
                    response = requests.post(TARGET_URL, data=form_data)
                if response.status_code != 200:
                    raise ExceptionHttpStatusCode(
                        "requests received {} status code /POST".format(response.status_code))
            except requests.exceptions.RequestException as e:
                logging.error(e)
                continue
            except ExceptionHttpStatusCode as e:
                logging.warning(e)
                continue
            else:
                response = response.text[-3000:]
                if "freebirdFormviewerViewResponseConfirmationMessage" in response:
                    ack_counter.count()
                    logging.info("response submitted ")
                else:
                    logging.warning("got a strange response from google forms")


def check_form_url(fbUrl=GROUP_URL):
    while True:
        response = httpRequest(fbUrl)
        soup = BeautifulSoup(response, 'html.parser')

        divs = soup.find_all('div', class_='_4bl9')

        for div in divs:
            hrefs = div.find_all('a')
            for href in hrefs:
                if "docs.google" in str(href):
                    href = str(href)
                    raw = href.split(';')[0]
                    raw = raw.rsplit("\"")[-1]
                    raw = raw.split("?", 1)[1][2:]
                    url = unquote(raw)
                    url = url.rsplit("&", 1)[0]
                    with urlLock:
                        target_url = url.rsplit("/", 1)[0] + "/formResponse?"

                    logging.info("synced google form url from fb")

        time.sleep(SYNC_SLEEP)


class SafeCounter(object):
    def __init__(self):
        self.cur_count = 0
        self.lock = threading.Lock()

    def count(self):
        with self.lock:
            self.cur_count += 1

    def getCount(self):
        with self.lock:
            return self.cur_count


if __name__ == "__main__":
    print("\t\t * TUC Secrets - spam edition *\n\n\n")
    logging.info("\n\n\n\n\n---------------- Session ----------------")

    messages = PriorityQueue(MEM_SIZE)
    postThread = None
    dataThread = None
    syncThread = None

    total_counter = SafeCounter()
    ack_counter = SafeCounter()

    try:
        print("start sync thread ...", end="")
        syncThread = Thread(target=check_form_url, daemon=True)
        syncThread.start()
        print("OK")

        print("start data thread ...", end="")
        dataThread = Thread(target=check_for_updates, args=(messages, 'http://www.tokoulouri.com'), daemon=True)
        dataThread.start()
        print("OK")

        print("start spam thread ...", end="")
        postThread = Thread(target=post_secret, args=(messages, total_counter, ack_counter), daemon=True)
        postThread.start()
        print("OK")

    except Exception as e:
        print("FAIL\n")
        logging.error(e)
        sys.exit(e)

    print("Ready\n\n")
    switch = True
    try:
        while True:
            if threading.activeCount() != 4:
                raise ExceptionThreadDied("Thread  died")

            mem_load = int(100 * (messages.qsize() / MEM_SIZE))
            total = total_counter.getCount()

            try:
                spam_meter = int(100 * (ack_counter.getCount() / total))
            except ZeroDivisionError:
                spam_meter = 0
                print("Waiting for stats...", flush=True, end="\r")
                continue

            display = "Workers {} | Memory Load: {:3d}% | Spam: {:3d}% | Total: {:6}  ".format(threading.activeCount(),
                                                                                               mem_load,
                                                                                               spam_meter, total)

            if switch:
                display = display + "[ ]"
                switch = False
            else:
                display = display + "[*]"
                switch = True

            print(display, flush=True, end="\r")
            time.sleep(MAIN_SLEEP)

    except KeyboardInterrupt as e:
        logging.info("session END")
        sys.stdout.flush()
        sys.exit("Bye")

    except ExceptionThreadDied as e:
        logging.error(e)
        sys.stdout.flush()
        sys.exit("Fatal error: " + str(e))
