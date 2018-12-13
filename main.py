import logging
import random
import re
import threading
import time
from queue import PriorityQueue, Empty, Full
from threading import Thread

import requests
from bs4 import BeautifulSoup
from newspaper import Article, ArticleException

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s (%(threadName)-10s)  "
                           "[%(levelname)-5.5s]  %(message)s",
                    datefmt='%Y-%m-%d %H:%M:%S', )

logging.getLogger(__name__)

MAX_SIZE = 1024  # queue max size
UPDATE_SLEEP = 60 * 5
STEP_SLEEP = 2
POST_SLEEP = 2
MAIN_SLEEP = 2

target_url = "https://docs.google.com/forms/d/e/1FAIpQLScsrsrBIRKqaULBKMilvcPyX_M_QOvgikO6Mq9aGUjNOe3NRg/viewform?fbclid=IwAR0xDS-97ME2RpVZ4di5BaAvcxzpskJbmKg-cpmFONREwVF_pBps3RtNNzk"

# remove facebook tracking id from url
if "?fbclid=" in target_url:
    target_url = target_url.rsplit("?", 1)[0]

# prepare response endpoint
target_url = target_url.rsplit("/", 1)[0] + "/formResponse?"

with open('names.txt', 'rb') as file:
    names = file.readlines()

# make pretty names
names = [name.decode('utf-8') for name in names]
names = [name[0].capitalize() + name[1:].lower() for name in names]

schools = ["ΜΠΔ", "ΗΜΜΥ", "ΑΡΜΗΧ", "ΜΗΧΟΠ", "ΜΗΠΕΡ"]

# make up friendly names for form attributes
form_metadata = {'school': 'entry.560704317',
                 'nickname': 'entry.1577379385',
                 'secret': 'entry.1868912204'
                 }


def httpRequest(url):
    response = None
    try:
        response = requests.get(url)
    except requests.exceptions.RequestException as e:
        logging.error(e)
    finally:
        if response:
            return response.text


def get_headline_url(url='http://www.tokoulouri.com'):
    koulouri_urls = []
    raw_html = httpRequest(url)

    soup = BeautifulSoup(raw_html, "html.parser")
    for ul in soup.find_all('ul', class_='latest-news'):
        for li in ul.find_all('li'):
            a = li.find('a')
            koulouri_urls.append(a.get_text())
    return koulouri_urls


def extractContent(url, lang='el'):
    text = ''
    try:
        article = Article(url, language=lang)
        article.download()
        article.parse()
    except ArticleException as e:
        logging.warning(e)
    else:
        text = article.text.strip()
    finally:
        return text, len(text)


def check_for_updates(text_queue):
    while True:
        urls = get_headline_url()
        for url in urls:
            text, size = extractContent(url)
            sentences = text.split('.')

            for sentence in sentences:
                if re.search("κουλούρι", sentence, re.IGNORECASE):
                    continue

                priority = random.randint(1, MAX_SIZE)
                try:
                    text_queue.put((priority, sentence), block=False)
                except Full:
                    logging.warning("text queue is full")
        time.sleep(UPDATE_SLEEP)


def post_secret(text_queue, total_counter, succe_counter):
    while True:
        try:
            secret = text_queue.get(block=False)
        except Empty:
            pass
        else:

            # make up random form data
            school_entry = random.choice(schools)
            nickname_entry = random.choice(names)
            secret_entry = secret[1]

            form_data = {form_metadata['school']: school_entry,
                         form_metadata['nickname']: nickname_entry,
                         form_metadata['secret']: secret_entry}

            try:
                response = requests.post(target_url, data=form_data)
            except requests.exceptions.RequestException as e:
                logging.error(e)
            else:
                if response:
                    response = response.text[-3000:]
                    if "freebirdFormviewerViewResponseConfirmationMessage" in response:
                        succe_counter.count()
                        pass
                    else:
                        logging.error("response not submitted! ")
            total_counter.count()
        finally:
            time.sleep(POST_SLEEP)


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
    print("\t\t * TUofC Secrets - spam edition *\n\n\n")

    text_queue = PriorityQueue(MAX_SIZE)

    print("start data thread ...", end='')
    try:
        dataThread = Thread(target=check_for_updates, args=(text_queue,))
        dataThread.daemon = True
        dataThread.start()
        time.sleep(5)
    except Exception as e:
        print("FAIL")
        logging.error(e)
    else:
        print("OK")

    total_counter = succe_counter = SafeCounter()

    postThread = None
    dataThread = None
    print("start spam thread ...", end="")
    try:
        postThread = Thread(target=post_secret, args=(text_queue, total_counter, succe_counter))
        postThread.daemon = True
        postThread.start()
        time.sleep(5)
    except Exception as e:
        print("FAIL")
        logging.error(e)
    else:
        print("OK")

    print("Ready BOOM\n\n")
    switch = True
    try:
        while True:
            t_count = threading.active_count()
            q_load = int(100 * (text_queue.qsize() / MAX_SIZE))
            total = total_counter.getCount()
            spam_meter = int(100 * (succe_counter.getCount() / total))

            if switch:
                print("  Threads: {:>2} | Mem: {:3d}% | Spam: {:3d}% | Total: {}".format(t_count, q_load,
                                                                                         spam_meter, total),
                      flush=True, end='\r')
                switch = False
            else:
                print("* Threads: {:>2} | Mem: {:3d}% | Spam: {:3d}% | Total: {}".format(t_count, q_load,
                                                                                         spam_meter, total),
                      flush=True, end='\r')
                switch = True

            if not (dataThread.is_alive() and postThread.is_alive()):
                logging.error('A thread died')
                break
            time.sleep(MAIN_SLEEP)
    except KeyboardInterrupt:
        pass
