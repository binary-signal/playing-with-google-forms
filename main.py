import logging
import random
import re
import threading
import time
from queue import PriorityQueue, Empty, Full
from threading import Thread
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup
from newspaper import Article, ArticleException

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s (%(threadName)-10s) [%(levelname)-5.5s]  %(message)s",
                    datefmt='%Y-%m-%d %H:%M:%S', )

logging.getLogger(__name__)


class ExceptionHttpStatusCode(Exception):
    pass


MAX_SIZE = 1024  # queue max size
UPDATE_SLEEP = 30
STEP_SLEEP = 2
POST_SLEEP = 2
MAIN_SLEEP = 2
URL_SYNC_SLEEP = 60

target_url = "https://docs.google.com/forms/d/e/1FAIpQLScsrsrBIRKqaULBKMilvcPyX_M_QOvgikO6Mq9aGUjNOe3NRg/viewform?fbclid=IwAR0xDS-97ME2RpVZ4di5BaAvcxzpskJbmKg-cpmFONREwVF_pBps3RtNNzk"
target_url = target_url.rsplit("/", 1)[0] + "/formResponse?"
urlLock = threading.Lock()

# make up friendly names for form attributes
form_metadata = {'school': 'entry.560704317',
                 'nickname': 'entry.1577379385',
                 'secret': 'entry.1868912204',
                 'email': 'emailAddress'
                 }


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
        if response:
            return response.text


def get_headline_url(url='http://www.tokoulouri.com'):
    koulouri_urls = []
    raw_html = httpRequest(url)

    if raw_html:
        soup = BeautifulSoup(raw_html, "html.parser")
        for ul in soup.find_all('ul', class_='latest-news'):
            for li in ul.find_all('li'):
                a = li.find('a')
                koulouri_urls.append(a['href'])

    return koulouri_urls


def extractContent(url, lang='el'):
    article = Article(url, language=lang)
    article.download()
    article.parse()
    text = article.text.strip()
    return text, len(text)


def check_for_updates(queue):
    while True:
        urls = get_headline_url()
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

                    priority = random.randint(1, MAX_SIZE)
                    try:
                        queue.put((priority, sentence), block=False)
                    except Full:
                        logging.warning("text queue is full")

                logging.info("added {} messages to queue".format(len(sentences)))
        time.sleep(UPDATE_SLEEP)


def post_secret(queue, total_counter, succe_counter):
    with open('names.txt', 'rb') as file:
        names = file.readlines()

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
            email_entry = "sakis@yahoo.com"
            school_entry = random.choice(schools)
            nickname_entry = random.choice(names)
            secret_entry = secret[1]

            form_data = {form_metadata['school']: school_entry,
                         form_metadata['nickname']: nickname_entry,
                         form_metadata['secret']: secret_entry,
                         form_metadata['email']: email_entry}

            time.sleep(random.randint(1, 3))
            try:
                total_counter.count()
                with urlLock:
                    response = requests.post(target_url, data=form_data)
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
                    succe_counter.count()
                    logging.info("response submitted ")
                else:
                    logging.error("got this strange response from google forms \n" + response)


def check_form_url(fbUrl='https://business.facebook.com/pg/TUCSecrets/about/'):
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

        time.sleep(URL_SYNC_SLEEP)


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
    logging.info("\n\n\n\n\n---------------- Session ----------------")

    text_queue = PriorityQueue(MAX_SIZE)
    postThread = None
    dataThread = None
    syncThread = None

    print("start sync thread ...", end='')
    try:
        syncThread = Thread(target=check_form_url)
        syncThread.daemon = True
        syncThread.start()
    except Exception as e:
        print("FAIL")
        logging.error(e)
    else:
        print("OK")

    print("start data thread ...", end='')
    try:
        dataThread = Thread(target=check_for_updates, args=(text_queue,))
        dataThread.daemon = True
        dataThread.start()
    except Exception as e:
        print("FAIL")
        logging.error(e)
    else:
        print("OK")

    total_counter = SafeCounter()
    succe_counter = SafeCounter()

    print("start spam thread ...", end="")
    try:
        postThread = Thread(target=post_secret, args=(text_queue, total_counter, succe_counter))
        postThread.daemon = True
        postThread.start()
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
            if total == 0:
                total = 0.000000001

            spam_meter = int(100 * (succe_counter.getCount() / total))

            if switch:
                print("Threads: {:>2} | Mem: {:3d}% | Spam: {:3d}% | Total: {:6}  [ ]".format(t_count, q_load,
                                                                                              spam_meter, total),
                      flush=True, end='\r')
                switch = False
            else:
                print("Threads: {:>2} | Mem: {:3d}% | Spam: {:3d}% | Total: {:6}  [*]".format(t_count, q_load,
                                                                                              spam_meter, total),
                      flush=True, end='\r')
                switch = True

            if not (dataThread.is_alive() and postThread.is_alive() and syncThread.is_alive()):
                logging.error('A thread died, terminating :(')
                break
            time.sleep(MAIN_SLEEP)
    except KeyboardInterrupt:
        logging.info("session END")
