from abc import ABCMeta, abstractmethod

from bs4 import BeautifulSoup


class BaseScaper(metaclass=ABCMeta):
    @abstractmethod
    def __init__(self):
        pass

    @abstractmethod
    def scrape(self):
        raise NotImplementedError


class Kolouri(BaseScaper):
    def __init__(self, page):
        self.page = page
        self.urls = []
        super().__init__()

    def scrape(self):
        if self.urls:
            self.urls.clear()

        soup = BeautifulSoup(self.page, "html.parser")
        for ul in soup.find_all('ul', class_='latest-news'):
            for li in ul.find_all('li'):
                a = li.find('a')
                self.urls.append(a['href'])

        return self.urls
