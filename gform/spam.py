# -*- coding: utf-8 -*-

import argparse
import datetime
import logging
import logging.handlers
import multiprocessing
import queue
import random
import string
import sys
import threading
import time
from collections import deque
from timeit import default_timer as timer

import requests
from newspaper import Article, ArticleException

from .exceptions import ExceptionHttpStatusCode, ExceptionThreadDied
from .scraper import Kolouri

rootLogger = logging.getLogger('')
rootLogger.setLevel(logging.INFO)

socketHandler = logging.handlers.SocketHandler('localhost', logging.handlers.DEFAULT_TCP_LOGGING_PORT)
rootLogger.addHandler(socketHandler)

logging.getLogger(__name__)

MEM_SIZE = 128  # max size for response queue

POST_SLEEP = 10
STATS_DELAY = 3
FETCH_DELAY = 30

form_metadata = {'school': 'entry.1328574731',  # make up friendly names for form attributes
                 'nickname': 'entry.657519342',
                 'secret': 'entry.1452404370',
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


def fetchResponces(q, target_url):
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
                    priority = random.randint(1, MEM_SIZE)
                    try:
                        q.put((priority, sentence), block=False)
                    except queue.Full:
                        logging.warning("text queue is full, waiting 30 sec")
                        time.sleep(30)

                # logging.info("added {} messages to queue".format(len(sentences)))
        time.sleep(FETCH_DELAY)


def post_secret(q, total_counter, ack_counter, url):
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
            secret = q.get(block=False)
        except queue.Empty:
            logging.warning("response queue is empty, sleep for 5 sec")
            time.sleep(5)
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

        total_counter.count()
        try:
            response = requests.post(url, data=form_data)

            if response.status_code != 200:
                raise ExceptionHttpStatusCode("requests received {} status code /POST".format(response.status_code))
        except requests.exceptions.RequestException as e:
            logging.error(e)
            continue
        except ExceptionHttpStatusCode as e:
            logging.warning(e)
            continue

        response = response.text[-3000:]
        if "freebirdFormviewerViewResponseConfirmationMessage" not in response:
            logging.warning("got a strange response from google forms")
            continue

        ack_counter.count()
        # logging.info("response submitted ")


class SafeCounter(object):
    def __init__(self):
        self.cur_count = 0
        self.lock = threading.Lock()

    def count(self):
        with self.lock:
            self.cur_count += 1

    def reset(self):
        with self.lock:
            self.cur_count = 0

    def get_count(self):
        with self.lock:
            return self.cur_count


def do_work(q, url):
    messages = queue.PriorityQueue(MEM_SIZE)

    total_counter = SafeCounter()
    ack_counter = SafeCounter()

    try:
        dataThread = threading.Thread(target=fetchResponces, args=(messages, 'http://www.tokoulouri.com'),
                                      daemon=True)
        dataThread.start()

        postThread = threading.Thread(target=post_secret, args=(messages, total_counter, ack_counter, url),
                                      daemon=True)
        postThread.start()
    except Exception as e:
        logging.error(e)
        sys.exit(e)

    try:
        while True:
            mem_load = int(100 * (messages.qsize() / MEM_SIZE))
            total = total_counter.get_count()
            ack = ack_counter.get_count()

            total_counter.reset()
            ack_counter.reset()

            #logging.info("total {:5} ack {:5d} meter".format(total, ack))
            try:
                spam_meter = int(100 * (ack / total))
            except ZeroDivisionError:
                q.put({
                    "thread": 0,
                    "mem_load": 0,
                    "spam_meter": 0,
                    "ack": 0,
                    "total": 0
                })
                time.sleep(STATS_DELAY)
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
            time.sleep(STATS_DELAY)
    except queue.Full:
        logging.error("status queue is full")
    except ExceptionThreadDied:
        pass
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.error(e)
        sys.stdout.flush()
        sys.exit("Fatal error: " + str(e))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("-w", action="store", dest="workers", help="number of worker process", type=int)
    parser.add_argument("URL", action="store", help="google form url ", type=str)

    args = parser.parse_args()

    if "docs.google.com/forms/" not in args.URL:
        sys.exit("Not supported URL")

    form_url = args.URL
    form_url = form_url.rsplit("/", 1)[0] + "/formResponse?"

    if not args.workers:
        cores = multiprocessing.cpu_count()
        workers = cores * 2
    else:
        workers = args.workers

    process_queue = multiprocessing.Queue()  # forward messages to main process

    responsesNum = 0
    attemptsNum = 0

    print("\n\n\t\t * Google Forms - spam edition *\n\n\n")
    logging.info("\n\n\n\n\n---------------- Session ----------------")
    print("url: {}\n\n".format(form_url))

    try:
        for w in range(1, workers + 1):
            p = multiprocessing.Process(target=do_work, args=(process_queue, form_url))
            p.daemon = True
            p.start()
            time.sleep(0.25)
            print("Workers ready {}".format(w), end="\r")

        t_start = timer()

        avg_buffer = deque([0 for i in range(1, workers + 1)])
        display = "Waiting for stats"
        while True:
            try:
                stat = process_queue.get(block=False)
            except queue.Empty:
                pass
            else:
                attemptsNum = attemptsNum + stat['total']
                responsesNum = responsesNum + stat['ack']

                avg_buffer.append(stat['mem_load'])
                avg_buffer.popleft()
                mem_load = int(sum(avg_buffer) / len(avg_buffer))

                display = "Workers {:3d} | Mem Load {:3d}% | Ack: {:3d} | " \
                          "Total: {:6} ".format(workers, mem_load,
                                                responsesNum,
                                                attemptsNum)
            finally:
                t_now = int(timer() - t_start)
                t_now = str(datetime.timedelta(seconds=t_now))
                print(display + "Uptime: {:10}".format(t_now), end="\r")
                time.sleep(0.25)
    except KeyboardInterrupt as e:
        logging.info("session END")
        sys.stdout.flush()
        sys.exit("Bye")
