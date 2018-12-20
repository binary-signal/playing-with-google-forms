# -*- coding: utf-8 -*-

import datetime
import logging
import multiprocessing
import random
import re
import string
import sys
import threading
import time
from collections import deque
from multiprocessing import Process, Queue
from queue import PriorityQueue, Empty, Full
from threading import Thread
from timeit import default_timer as timer
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup
from newspaper import Article, ArticleException

from .exceptions import ExceptionHttpStatusCode, ExceptionThreadDied
from .log import *
from .scraper import Kolouri

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(process)d %(threadName)-10s [%(levelname)-5.5s]  %(message)s",
                    datefmt='%Y-%m-%d %H:%M:%S', )

logging.getLogger(__name__)

MEM_SIZE = 128  # queue max size

# FIXME change sync time to 120 sec
SYNC_SLEEP = 120  # sleep time intervals for threads
STEP_SLEEP = 2
POST_SLEEP = 2
MAIN_SLEEP = 3
UPDATE_SLEEP = 30

GROUP_URL = "https://www.facebook.com/pg/TUCSecrets/about/"
TARGET_URL = "https://docs.google.com/forms/d/e/1FAIpQLSedrGe0vpdK2FfwdpMTU1VUl8AEuYquC8UeH4atA66hUA5TRQ/viewform"

# TARGET_URL = "https://docs.google.com/forms/d/e/1FAIpQLSe1Pdyl6a-Ba5qXtNFKyXy82Gwsrwpmc616q1CrgF1aAoP3GA/viewform"
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


def scrapePage(url, pageScraper):
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
        urls = scrapePage(target_url, Kolouri)
        # logging.info("found {} urls".format(len(urls)))

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

                # logging.info("added {} messages to queue".format(len(sentences)))
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

        response = response.text[-3000:]
        if "freebirdFormviewerViewResponseConfirmationMessage" in response:
            ack_counter.count()
            # logging.info("response submitted ")
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

    def count_many(self, n):
        with self.lock:
            self.cur_count += n

    def getCount(self):
        with self.lock:
            return self.cur_count


def do_work(q):
    messages = PriorityQueue(MEM_SIZE)
    postThread = None
    dataThread = None

    total_counter = SafeCounter()
    ack_counter = SafeCounter()

    try:
        # print("start data thread ...", end="")
        dataThread = Thread(target=check_for_updates, args=(messages, 'http://www.tokoulouri.com'), daemon=True)
        dataThread.start()
        # print("OK")

        # print("start spam thread ...", end="")
        postThread = Thread(target=post_secret, args=(messages, total_counter, ack_counter), daemon=True)
        postThread.start()
        # print("OK")

    except Exception as e:
        print("FAIL\n")
        logging.error(e)
        sys.exit(e)

    try:
        while True:
            mem_load = int(100 * (messages.qsize() / MEM_SIZE))
            total = total_counter.getCount()
            ack = ack_counter.getCount()

            try:
                spam_meter = int(100 * (ack / total))
            except ZeroDivisionError:
                q.put(None)
                time.sleep(MAIN_SLEEP)
                continue

            threads = threading.activeCount()
            if threads != 4:
                raise ExceptionThreadDied("Thread  died\n")

            stats = {
                "thread": threads,
                "mem_load": mem_load,
                "spam_meter": spam_meter,
                "ack": ack,
                "total": total
            }
            q.put(stats)

            time.sleep(MAIN_SLEEP)
    except Full:
        logging.error("put error proccess queue")
    except ExceptionThreadDied:
        pass

    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.error(e)
        sys.stdout.flush()
        sys.exit("Fatal error: " + str(e))


if __name__ == "__main__":
    print("\t\t * TUC Secrets - spam edition *\n\n\n")
    logging.info("\n\n\n\n\n---------------- Session ----------------")
    process_queue = Queue()

    cores = None
    if not cores:
        cores = multiprocessing.cpu_count()
    workers = cores * 2
    total_counter = SafeCounter()
    ack_counter = SafeCounter()
    switch = True

    print("start sync thread ...", end="")
    try:
        syncThread = Thread(target=check_form_url, daemon=True)
        syncThread.start()
        sys.stdout.flush()
        print("OK\n")
    except Exception as e:
        print("FAIL\n")
        logging.error(e)
        sys.exit(e)

    try:
        for w in range(1, workers + 1):
            p = Process(target=do_work, args=(process_queue,))
            p.daemon = True
            p.start()
            time.sleep(0.2)
            print("Workers ready {}".format(w), end="\r")

        t_start = timer()

        avg_buffer = deque([0 for i in range(1, workers + 1)])
        display = "Waiting for stats"
        while True:
            try:
                stat = process_queue.get(block=False)
            except Empty:
                pass
            else:
                if stat:
                    ack_counter.count_many(stat['ack'])
                    total_counter.count_many(stat['total'])

                    avg_buffer.append(stat['mem_load'])
                    avg_buffer.popleft()
                    mem_load = int(sum(avg_buffer) / len(avg_buffer))
                    t_now = int(timer() - t_start)

                    t_now = str(datetime.timedelta(seconds=t_now))

                    display = "Workers {:3d} | Mem Load {:3d}% |Ack: {:3d} | Total: {:6} {} \n".format(workers,
                                                                                                       mem_load,
                                                                                                       ack_counter.getCount(),
                                                                                                       total_counter.getCount(),
                                                                                                       t_now)

                    if switch:
                        display = display + "[ ] "
                        switch = False
                    else:
                        display = display + "[*] "
                        switch = True

            finally:

                print(display, end="\r")
                time.sleep(0.2)
    except KeyboardInterrupt as e:
        logging.info("session END")
        sys.stdout.flush()
        sys.exit("Bye")
